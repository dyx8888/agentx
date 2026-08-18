import { expect, test } from '@playwright/test';

const FRONTEND_URL = process.env.PUBLIC_DEMO_FRONTEND_URL || 'http://localhost:3000';
const LOCAL_HOSTS = new Set(['localhost', '127.0.0.1', '::1', '[::1]']);

function parseRequestUrl(request) {
  try {
    return new URL(request.url());
  } catch {
    return null;
  }
}

function isLocalBrowserRequest(request) {
  const url = parseRequestUrl(request);
  if (!url || !['http:', 'https:', 'ws:', 'wss:'].includes(url.protocol)) {
    return true;
  }
  return LOCAL_HOSTS.has(url.hostname);
}

function requestSummary(request) {
  const url = parseRequestUrl(request);
  if (!url) return `${request.method()} ${request.url()}`;
  return `${request.method()} ${url.protocol}//${url.host}${url.pathname}`;
}

function isChatPost(request) {
  const url = parseRequestUrl(request);
  if (!url) return false;
  return request.method() === 'POST' && url.pathname.replace(/\/+$/, '') === '/api/chat';
}

function isExecutionServiceRequest(request) {
  const url = parseRequestUrl(request);
  if (!url) return false;
  const target = `${url.host}${url.pathname}`.toLowerCase();
  const blockedFragments = [
    '/api/rag/search',
    '/api/knowledge/search',
    '/api/kol',
    '/api/report',
    'kol-search',
    'report-server',
    'milvus',
  ];
  return blockedFragments.some((fragment) => target.includes(fragment));
}

async function registerSmokeUser(request, { username, email, password }) {
  const response = await request.post(`${FRONTEND_URL}/api/auth/users/register`, {
    data: {
      username,
      email,
      password,
      company_name: `${username} workspace`,
      brand_name: username,
      category: 'smoke',
    },
  });
  expect(response.status(), await response.text()).toBeLessThan(300);
}

async function loginThroughFrontend(page, { username, password }) {
  await page.goto(`${FRONTEND_URL}/login`);
  await page.evaluate(() => localStorage.clear());

  await page.locator('#email').fill(username);
  await page.locator('#password').fill(password);

  const loginResponse = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === '/api/auth/token' && response.request().method() === 'POST';
  });
  await page.locator('button[type="submit"]').click();
  expect((await loginResponse).status()).toBe(200);
}

test('public-demo lightweight chat entry initializes without sending chat or external requests', async ({ page, request }) => {
  const seenRequests = [];
  const consoleErrors = [];
  const pageErrors = [];
  let collectPageErrors = false;
  page.on('request', (browserRequest) => seenRequests.push(browserRequest));
  page.on('console', (message) => {
    if (collectPageErrors && message.type() === 'error') {
      consoleErrors.push(message.text());
    }
  });
  page.on('pageerror', (error) => {
    if (collectPageErrors) {
      pageErrors.push(error.message);
    }
  });

  const suffix = `${Date.now()}${Math.random().toString(36).slice(2, 8)}`;
  const username = `smokechat${suffix}`;
  const password = `LocalSmoke${suffix}!`;
  const email = `agentx-smoke-chat-${suffix}@example.test`;

  await registerSmokeUser(request, { username, email, password });

  const conversationsResponse = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return (
      url.pathname === '/api/conversations' &&
      url.searchParams.get('limit') === '50' &&
      response.request().method() === 'GET'
    );
  });

  await loginThroughFrontend(page, { username, password });

  const conversations = await conversationsResponse;
  expect(conversations.status()).toBe(200);
  const conversationsBody = await conversations.json();
  expect(conversationsBody.total).toBe(0);
  expect(conversationsBody.items).toEqual([]);

  await expect(page).toHaveURL(`${FRONTEND_URL}/`);
  collectPageErrors = true;
  await expect(page.locator('aside')).toBeVisible();
  await expect(page.getByText('还没有对话')).toBeVisible();

  const input = page.locator('textarea').first();
  await expect(input).toBeVisible();

  const composer = input.locator('xpath=ancestor::div[contains(@class, "rounded-2xl")][1]');
  const sendButton = composer.locator('button').last();
  await expect(sendButton).toBeVisible();
  await expect(sendButton).toBeDisabled();

  await page.waitForTimeout(1000);

  expect(seenRequests.filter(isChatPost).map(requestSummary)).toEqual([]);
  expect(seenRequests.filter((req) => !isLocalBrowserRequest(req)).map(requestSummary)).toEqual([]);
  expect(seenRequests.filter(isExecutionServiceRequest).map(requestSummary)).toEqual([]);
  expect(consoleErrors).toEqual([]);
  expect(pageErrors).toEqual([]);
});
