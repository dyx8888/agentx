import { chromium, expect, test } from '@playwright/test';
import http from 'node:http';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const repoRoot = path.resolve(__dirname, '../..');
const extensionPath = path.join(repoRoot, 'browser-extension', 'agentx-connector');
const fixturePath = path.join(__dirname, 'fixtures', 'agentx-connector-page.html');

test.describe('AgentX browser connector extension', () => {
  test('loads the MV3 extension and ingests sanitized allowlisted API captures', async () => {
    test.setTimeout(60_000);

    const ingest = await createIngestServer();
    const userDataDir = await fs.mkdtemp(path.join(os.tmpdir(), 'agentx-connector-e2e-'));
    const context = await chromium.launchPersistentContext(userDataDir, {
      channel: process.env.PLAYWRIGHT_EXTENSION_CHANNEL || 'msedge',
      headless: false,
      args: [
        `--disable-extensions-except=${extensionPath}`,
        `--load-extension=${extensionPath}`
      ]
    });

    try {
      const platformRequests = [];
      const worker = await waitForExtensionWorker(context);
      const storedSettings = await worker.evaluate(async (settings) => {
        const storageGet = (keys) => new Promise((resolve, reject) => {
          chrome.storage.local.get(keys, (value) => {
            if (chrome.runtime.lastError) {
              reject(new Error(chrome.runtime.lastError.message));
              return;
            }
            resolve(value);
          });
        });
        const storageSet = (value) => new Promise((resolve, reject) => {
          chrome.storage.local.set(value, () => {
            if (chrome.runtime.lastError) {
              reject(new Error(chrome.runtime.lastError.message));
              return;
            }
            resolve();
          });
        });

        const startedAt = Date.now();
        while (!(await storageGet(['settings'])).settings) {
          if (Date.now() - startedAt > 5000) {
            throw new Error('extension settings were not initialized');
          }
          await new Promise((resolve) => setTimeout(resolve, 50));
        }

        await storageSet({ settings, deliveries: [] });
        return storageGet(['settings']);
      }, { enabled: true, endpoint: ingest.endpoint });
      expect(storedSettings.settings.endpoint).toBe(ingest.endpoint);

      const html = await fs.readFile(fixturePath, 'utf8');
      await context.route('https://buyin.jinritemai.com/test-fixtures/agentx-connector.html', async (route) => {
        await route.fulfill({ status: 200, contentType: 'text/html', body: html });
      });
      await context.route('https://buyin.jinritemai.com/square_pc_api/square/search_feed_author**', async (route) => {
        rememberPlatformRequest(platformRequests, route);
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            items: [
              {
                nickname: 'Safe Creator',
                follower_count: 12345,
                token: 'fetch-token-secret',
                password: 'fetch-password-secret',
                captcha_code: '778899',
                payment_card: '4111 1111 1111 1111'
              }
            ],
            public_note: 'safe response value'
          })
        });
      });
      await context.route('https://buyin.jinritemai.com/apply_sample_pc_api/sample/apply**', async (route) => {
        rememberPlatformRequest(platformRequests, route);
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            sample_application: {
              status: 'received',
              creator_name: 'Safe Post Creator'
            }
          })
        });
      });
      await context.route('https://buyin.jinritemai.com/creative_radar_api/radar/list**', async (route) => {
        rememberPlatformRequest(platformRequests, route);
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            creators: [
              {
                nickname: 'XHR Creator',
                session_id: 'xhr-session-secret',
                credential: 'xhr-credential-secret'
              }
            ]
          })
        });
      });
      await context.route('https://buyin.jinritemai.com/public/not-allowlisted**', async (route) => {
        rememberPlatformRequest(platformRequests, route);
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ ignored: true, token: 'blocked-token-secret' })
        });
      });

      const page = await context.newPage();
      await page.goto('https://buyin.jinritemai.com/test-fixtures/agentx-connector.html');
      await expect(page.locator('body')).toHaveAttribute('data-agentx-fixture-done', 'true');

      let captures;
      try {
        captures = await ingest.waitForCount(2);
      } catch (error) {
        const extensionStorage = await worker.evaluate(async () => {
          return chrome.storage.local.get(['deliveries', 'lastDelivery']);
        });
        const pageState = await page.evaluate(() => ({
          injected: Boolean(window.__AGENTX_CONNECTOR_INJECTED__),
          fixtureDone: document.body.dataset.agentxFixtureDone || null,
          fixtureError: document.body.dataset.agentxFixtureError || null
        }));
        throw new Error(`${error.message}; page=${JSON.stringify(pageState)}; storage=${JSON.stringify(extensionStorage)}`);
      }
      expect(captures).toHaveLength(2);

      const fetchCapture = captures.find((capture) => capture.api.url.endsWith('/square_pc_api/square/search_feed_author'));
      const postCapture = captures.find((capture) => capture.api.url.endsWith('/apply_sample_pc_api/sample/apply'));
      const xhrCapture = captures.find((capture) => capture.api.captured_from === 'xmlhttprequest');

      expect(fetchCapture).toMatchObject({
        connector: { source: 'chrome-extension-mv3', mode: 'readonly' },
        api: {
          url: 'https://buyin.jinritemai.com/square_pc_api/square/search_feed_author',
          method: 'GET',
          status_code: 200,
          matched_rule: 'buyin-api',
          response_mime: 'application/json',
          captured_from: 'fetch'
        },
        policy: {
          whitelist_rule: 'buyin-api',
          contains_credentials: false,
          contains_sensitive_fields: false,
          platform_write_operation: false
        }
      });
      expect(xhrCapture).toMatchObject({
        api: {
          url: 'https://buyin.jinritemai.com/creative_radar_api/radar/list',
          matched_rule: 'buyin-api',
          captured_from: 'xmlhttprequest'
        }
      });
      expect(postCapture).toBeUndefined();

      expect(fetchCapture.data.value.items[0]).toMatchObject({
        nickname: 'Safe Creator',
        follower_count: 12345,
        token: '[REDACTED]',
        password: '[REDACTED]',
        captcha_code: '[REDACTED]',
        payment_card: '[REDACTED]'
      });
      expect(xhrCapture.data.value.creators[0]).toMatchObject({
        nickname: 'XHR Creator',
        session_id: '[REDACTED]',
        credential: '[REDACTED]'
      });
      const postPlatformRequest = platformRequests.find((request) => request.url.includes('/apply_sample_pc_api/sample/apply'));
      expect(postPlatformRequest).toMatchObject({
        method: 'POST',
        postData: expect.stringContaining('request-body-should-not-be-collected')
      });
      expect(postPlatformRequest.headers.authorization).toContain('post-authorization-should-not-be-collected');
      expect(platformRequests.some((request) => String(request.headers.cookie || '').includes('platform-cookie-should-not-be-collected'))).toBe(true);

      const serialized = JSON.stringify(captures);
      expect(serialized).not.toContain('should-not-be-collected');
      expect(serialized).not.toContain('should-not-leak');
      expect(serialized).not.toContain('platform-cookie-should-not-be-collected');
      expect(serialized).not.toContain('post-authorization-should-not-be-collected');
      expect(serialized).not.toContain('request-body-should-not-be-collected');
      expect(serialized).not.toContain('Safe Post Creator');
      expect(serialized).not.toContain('fetch-token-secret');
      expect(serialized).not.toContain('fetch-password-secret');
      expect(serialized).not.toContain('778899');
      expect(serialized).not.toContain('4111 1111 1111 1111');
      expect(serialized).not.toContain('xhr-session-secret');
      expect(serialized).not.toContain('xhr-credential-secret');
      expect(serialized).not.toContain('blocked-token-secret');
      expect(captures.every((capture) => !capture.api.url.includes('/public/not-allowlisted'))).toBe(true);
    } finally {
      await context.close();
      await ingest.close();
      await fs.rm(userDataDir, { recursive: true, force: true });
    }
  });
});

async function waitForExtensionWorker(context) {
  const existing = context.serviceWorkers()[0];
  if (existing) {
    return existing;
  }
  return context.waitForEvent('serviceworker', { timeout: 10_000 });
}

function rememberPlatformRequest(platformRequests, route) {
  const request = route.request();
  platformRequests.push({
    url: request.url(),
    method: request.method(),
    headers: request.headers(),
    postData: request.postData()
  });
}

function createIngestServer() {
  const captures = [];

  const server = http.createServer((request, response) => {
    if (request.method === 'OPTIONS') {
      response.writeHead(204, {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'content-type,x-agentx-connector-version',
        'Access-Control-Allow-Methods': 'POST,OPTIONS'
      });
      response.end();
      return;
    }

    if (request.method !== 'POST' || request.url !== '/api/browser-connector/ingest') {
      response.writeHead(404, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({ detail: 'not found' }));
      return;
    }

    let body = '';
    request.setEncoding('utf8');
    request.on('data', (chunk) => {
      body += chunk;
    });
    request.on('end', () => {
      captures.push(JSON.parse(body));
      response.writeHead(202, {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*'
      });
      response.end(JSON.stringify({ status: 'accepted' }));
    });
  });

  return new Promise((resolve, reject) => {
    server.on('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const address = server.address();
      resolve({
        endpoint: `http://127.0.0.1:${address.port}/api/browser-connector/ingest`,
        async waitForCount(count, timeoutMs = 10_000) {
          const startedAt = Date.now();
          while (captures.length < count) {
            if (Date.now() - startedAt > timeoutMs) {
              throw new Error(`Timed out waiting for ${count} captures; got ${captures.length}`);
            }
            await new Promise((pollResolve) => setTimeout(pollResolve, 50));
          }
          return captures.slice();
        },
        close() {
          return new Promise((closeResolve, closeReject) => {
            server.close((error) => {
              if (error) {
                closeReject(error);
                return;
              }
              closeResolve();
            });
          });
        }
      });
    });
  });
}
