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

      const captureJob = await openExtensionPage(context, worker, {
        type: 'AGENTX_CONNECTOR_SET_CAPTURE_JOB',
        captureJob: {
          id: 901,
          purpose: 'generic_evidence',
          target_host: 'buyin.jinritemai.com',
          target_path_prefix: '/test-fixtures',
          expires_at: new Date(Date.now() + 60_000).toISOString(),
          ticket_expires_at: new Date(Date.now() + 60_000).toISOString(),
          capability_ticket: 'test-capture-job-ticket'
        }
      });
      expect(captureJob.ok).toBe(true);

      const sessionState = await worker.evaluate(() =>
        chrome.storage.session.get(['captureJobs', 'activeCaptureJobId'])
      );
      expect(sessionState.activeCaptureJobId).toBe(901);
      expect(sessionState.captureJobs).toEqual([
        expect.objectContaining({ id: 901, capability_ticket: 'test-capture-job-ticket' })
      ]);

      const expiredCaptureJob = await openExtensionPage(context, worker, {
        type: 'AGENTX_CONNECTOR_SET_CAPTURE_JOB',
        captureJob: {
          id: 902,
          purpose: 'generic_evidence',
          target_host: 'buyin.jinritemai.com',
          target_path_prefix: '/test-fixtures',
          expires_at: new Date(Date.now() + 60_000).toISOString(),
          ticket_expires_at: new Date(Date.now() - 1_000).toISOString(),
          capability_ticket: 'expired-capture-job-ticket'
        }
      });
      expect(expiredCaptureJob.ok).toBe(false);

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
        page: {
          url: 'https://buyin.jinritemai.com/test-fixtures/agentx-connector.html'
        },
        capture_job_id: 901,
        capability_ticket: 'test-capture-job-ticket',
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
        follower_count: 12345
      });
      expect(fetchCapture.data.value.items[0]).not.toHaveProperty('token');
      expect(fetchCapture.data.value.items[0]).not.toHaveProperty('password');
      expect(fetchCapture.data.value.items[0]).not.toHaveProperty('captcha_code');
      expect(fetchCapture.data.value.items[0]).not.toHaveProperty('payment_card');
      expect(xhrCapture.data.value.creators[0]).toMatchObject({
        nickname: 'XHR Creator'
      });
      expect(xhrCapture.data.value.creators[0]).not.toHaveProperty('session_id');
      expect(xhrCapture.data.value.creators[0]).not.toHaveProperty('credential');
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

  test('captures a selected generic HTTPS page and same-origin read-only API only', async () => {
    test.setTimeout(60_000);

    const ingest = await createIngestServer();
    const userDataDir = await fs.mkdtemp(path.join(os.tmpdir(), 'agentx-connector-generic-e2e-'));
    const context = await chromium.launchPersistentContext(userDataDir, {
      channel: process.env.PLAYWRIGHT_EXTENSION_CHANNEL || 'msedge',
      headless: false,
      args: [
        `--disable-extensions-except=${extensionPath}`,
        `--load-extension=${extensionPath}`
      ]
    });

    try {
      const worker = await waitForExtensionWorker(context);
      await worker.evaluate(async (settings) => {
        const storageGet = (keys) => new Promise((resolve, reject) => {
          chrome.storage.local.get(keys, (value) => {
            if (chrome.runtime.lastError) {
              reject(new Error(chrome.runtime.lastError.message));
              return;
            }
            resolve(value);
          });
        });
        const startedAt = Date.now();
        while (!(await storageGet(['settings'])).settings) {
          if (Date.now() - startedAt > 5_000) {
            throw new Error('extension settings were not initialized');
          }
          await new Promise((resolve) => setTimeout(resolve, 50));
        }
        await chrome.storage.local.set({ settings, deliveries: [] });
      }, { enabled: true, endpoint: ingest.endpoint });

      await context.route('https://generic.agentx.test/generic-fixture', async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'text/html',
          body: `<!doctype html><html><head><title>Public Catalog</title><meta name="description" content="Safe public catalog"><script type="application/ld+json">${JSON.stringify({ name: 'Safe Public Item', email: 'private@example.test' })}</script></head><body><h1>Public Catalog</h1><p>Visible public description.</p><p>Contact private@example.test or 13800138000.</p><script>
            window.addEventListener('agentx-browser-connector-enable-generic-api', async () => {
              await fetch('/api/public/catalog');
              await fetch('/api/private/message');
              await fetch('/api/public/write', { method: 'POST', body: JSON.stringify({ should_not_capture: true }) });
              document.body.dataset.genericFixtureDone = 'true';
            });
          </script></body></html>`
        });
      });
      await context.route('https://generic.agentx.test/api/public/catalog', async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ items: [{ name: 'Safe Public Item', description: 'Public value', email: 'private@example.test', token: 'must-not-forward' }] })
        });
      });
      await context.route('https://generic.agentx.test/api/private/message', async (route) => {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ messages: ['must not capture'] }) });
      });
      await context.route('https://generic.agentx.test/api/public/write', async (route) => {
        await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ written: true }) });
      });

      const page = await context.newPage();
      await page.goto('https://generic.agentx.test/generic-fixture', { waitUntil: 'domcontentloaded', timeout: 10_000 });
      await expect(page.locator('body')).toContainText('Public Catalog');

      const tabId = await worker.evaluate(async () => {
        const [tab] = await chrome.tabs.query({ url: 'https://generic.agentx.test/generic-fixture' });
        if (!tab || !Number.isInteger(tab.id)) {
          throw new Error('generic fixture tab is unavailable');
        }
        return tab.id;
      });
      const extensionOrigin = `chrome-extension://${new URL(worker.url()).hostname}`;
      const popup = await context.newPage();
      await popup.goto(`${extensionOrigin}/popup.html`, { waitUntil: 'domcontentloaded' });
      const enabled = await popup.evaluate(async (targetTabId) => {
        const within = (promise, label) => Promise.race([
          promise,
          new Promise((_, reject) => setTimeout(() => reject(new Error(`${label} timed out`)), 5_000))
        ]);
        const enabled = await within(new Promise((resolve, reject) => {
          chrome.runtime.sendMessage({ type: 'AGENTX_CONNECTOR_ENABLE_GENERIC_CAPTURE', tabId: targetTabId }, (result) => {
            if (chrome.runtime.lastError) {
              reject(new Error(chrome.runtime.lastError.message));
              return;
            }
            resolve(result);
          });
        }), 'generic capture enable');
        return enabled;
      }, tabId);
      expect(enabled.ok).toBe(true);
      await page.waitForFunction(() => Boolean(window.__AGENTX_CONNECTOR_INJECTED__), undefined, { timeout: 5_000 });
      const capture = await popup.evaluate(async (targetTabId) => {
        const within = (promise, label) => Promise.race([
          promise,
          new Promise((_, reject) => setTimeout(() => reject(new Error(`${label} timed out`)), 5_000))
        ]);
        return within(new Promise((resolve, reject) => {
          chrome.runtime.sendMessage({ type: 'AGENTX_CONNECTOR_CAPTURE_CURRENT_PAGE', tabId: targetTabId }, (result) => {
            if (chrome.runtime.lastError) {
              reject(new Error(chrome.runtime.lastError.message));
              return;
            }
            resolve(result);
          });
        }), 'content-script capture command');
      }, tabId);
      await popup.close();
      expect(capture.ok).toBe(true);
      await expect(page.locator('body')).toHaveAttribute('data-generic-fixture-done', 'true');

      let captures;
      try {
        captures = await ingest.waitForCount(2);
      } catch (error) {
        const storage = await worker.evaluate(() => chrome.storage.local.get(['deliveries', 'lastDelivery']));
        throw new Error(`${error.message}; storage=${JSON.stringify(storage)}`);
      }
      expect(captures).toHaveLength(2);
      const pageCapture = captures.find((capture) => capture.api.matched_rule === 'generic-web-page');
      const apiCapture = captures.find((capture) => capture.api.matched_rule === 'generic-api-capture');
      expect(pageCapture).toBeTruthy();
      expect(apiCapture).toBeTruthy();
      expect(pageCapture.data.kind).toBe('generic_web_page');
      expect(pageCapture.data.visible_text).toContain('Visible public description.');
      expect(pageCapture.data.visible_text).not.toContain('private@example.test');
      expect(pageCapture.data.visible_text).not.toContain('13800138000');
      expect(apiCapture.data.value.items[0]).toMatchObject({ name: 'Safe Public Item', description: 'Public value' });
      expect(apiCapture.data.value.items[0]).not.toHaveProperty('email');
      expect(apiCapture.data.value.items[0]).not.toHaveProperty('token');
      expect(captures.every((capture) => !capture.api.url.includes('/private/message'))).toBe(true);
      expect(captures.every((capture) => !capture.api.url.includes('/public/write'))).toBe(true);
    } finally {
      await context.close();
      await ingest.close();
      await fs.rm(userDataDir, { recursive: true, force: true });
    }
  });
});

test.describe('AgentX browser connector endpoint synchronization', () => {
  test('uses the current AgentX Preview origin after the extension is installed', async () => {
    test.setTimeout(60_000);

    const userDataDir = await fs.mkdtemp(path.join(os.tmpdir(), 'agentx-connector-endpoint-'));
    const context = await chromium.launchPersistentContext(userDataDir, {
      channel: process.env.PLAYWRIGHT_EXTENSION_CHANNEL || 'msedge',
      headless: false,
      args: [
        `--disable-extensions-except=${extensionPath}`,
        `--load-extension=${extensionPath}`
      ]
    });
    const previewUrl = 'https://agentx-e2e-dyx8888s-projects.vercel.app/';
    const expectedEndpoint = `${previewUrl}api/browser-connector/ingest`;

    try {
      const worker = await waitForExtensionWorker(context);
      await context.route(`${previewUrl}**`, async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'text/html',
          body: '<!doctype html><title>AgentX test</title><main>AgentX</main>'
        });
      });
      const page = await context.newPage();
      await page.goto(previewUrl, { waitUntil: 'domcontentloaded' });

      await expect.poll(async () => worker.evaluate(async () => {
        const { settings } = await chrome.storage.local.get(['settings']);
        return settings?.endpoint || '';
      })).toBe(expectedEndpoint);
    } finally {
      await context.close();
      await fs.rm(userDataDir, { recursive: true, force: true });
    }
  });

  test('prefers the most recently used AgentX Preview when multiple Preview tabs are open', async () => {
    test.setTimeout(60_000);

    const userDataDir = await fs.mkdtemp(path.join(os.tmpdir(), 'agentx-connector-preview-selection-'));
    const context = await chromium.launchPersistentContext(userDataDir, {
      channel: process.env.PLAYWRIGHT_EXTENSION_CHANNEL || 'msedge',
      headless: false,
      args: [
        `--disable-extensions-except=${extensionPath}`,
        `--load-extension=${extensionPath}`
      ]
    });
    const oldPreviewUrl = 'https://agentx-old-dyx8888s-projects.vercel.app/';
    const latestPreviewUrl = 'https://agentx-latest-dyx8888s-projects.vercel.app/';
    const expectedEndpoint = `${latestPreviewUrl}api/browser-connector/ingest`;

    try {
      const worker = await waitForExtensionWorker(context);
      await context.route('https://agentx-*-dyx8888s-projects.vercel.app/**', async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'text/html',
          body: '<!doctype html><title>AgentX test</title><main>AgentX</main>'
        });
      });
      const oldPage = await context.newPage();
      await oldPage.goto(oldPreviewUrl, { waitUntil: 'domcontentloaded' });
      const latestPage = await context.newPage();
      await latestPage.goto(latestPreviewUrl, { waitUntil: 'domcontentloaded' });
      await latestPage.bringToFront();

      const popup = await context.newPage();
      await popup.goto(`chrome-extension://${new URL(worker.url()).hostname}/popup.html`, {
        waitUntil: 'domcontentloaded'
      });
      await expect.poll(async () => worker.evaluate(async () => {
        const { settings } = await chrome.storage.local.get(['settings']);
        return settings?.endpoint || '';
      })).toBe(expectedEndpoint);
      await popup.close();
    } finally {
      await context.close();
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

async function openExtensionPage(context, worker, message) {
  const extensionOrigin = `chrome-extension://${new URL(worker.url()).hostname}`;
  const page = await context.newPage();
  await page.goto(`${extensionOrigin}/popup.html`, { waitUntil: 'domcontentloaded' });
  try {
    return await page.evaluate((payload) => new Promise((resolve, reject) => {
      chrome.runtime.sendMessage(payload, (result) => {
        if (chrome.runtime.lastError) {
          reject(new Error(chrome.runtime.lastError.message));
          return;
        }
        resolve(result);
      });
    }), message);
  } finally {
    await page.close();
  }
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
