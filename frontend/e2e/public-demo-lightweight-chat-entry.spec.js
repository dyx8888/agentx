import { expect, test } from '@playwright/test';

const FRONTEND_URL = process.env.PUBLIC_DEMO_FRONTEND_URL || 'http://localhost:5173';
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

function isConversationCreatePost(request) {
  const url = parseRequestUrl(request);
  if (!url) return false;
  return request.method() === 'POST' && url.pathname.replace(/\/+$/, '') === '/api/conversations';
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

function configuredSmokeUser() {
  return {
    username: process.env.PUBLIC_DEMO_E2E_CHAT_USERNAME || '',
    password: process.env.PUBLIC_DEMO_E2E_CHAT_PASSWORD || '',
  };
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

test('public-demo lightweight chat entry initializes without sending chat or external requests', async ({ page }) => {
  const seenRequests = [];
  const blockedChatRequests = [];
  const blockedConversationCreates = [];
  const blockedExecutionRequests = [];
  const blockedExternalRequests = [];
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

  await page.route('**/*', async (route) => {
    const browserRequest = route.request();
    if (!isLocalBrowserRequest(browserRequest)) {
      blockedExternalRequests.push(browserRequest);
      await route.abort('blockedbyclient');
      return;
    }
    if (isChatPost(browserRequest)) {
      blockedChatRequests.push(browserRequest);
      await route.abort('blockedbyclient');
      return;
    }
    if (isConversationCreatePost(browserRequest)) {
      blockedConversationCreates.push(browserRequest);
      await route.abort('blockedbyclient');
      return;
    }
    if (isExecutionServiceRequest(browserRequest)) {
      blockedExecutionRequests.push(browserRequest);
      await route.abort('blockedbyclient');
      return;
    }
    await route.continue();
  });

  const { username, password } = configuredSmokeUser();
  test.skip(
    !username || !password,
    'Set PUBLIC_DEMO_E2E_CHAT_USERNAME and PUBLIC_DEMO_E2E_CHAT_PASSWORD to a pre-verified local smoke user',
  );

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

  const suggestionCard = page.getByRole('button', { name: /达人搜索与邀约草稿/ });
  await suggestionCard.click();
  await expect(input).toHaveValue('只基于我的达人库搜索护肤类小红书达人，并生成待审核邀约草稿');
  await expect(sendButton).toBeEnabled();

  await page.waitForTimeout(1000);

  expect(blockedChatRequests.map(requestSummary)).toEqual([]);
  expect(blockedConversationCreates.map(requestSummary)).toEqual([]);
  expect(blockedExecutionRequests.map(requestSummary)).toEqual([]);
  expect(blockedExternalRequests.map(requestSummary)).toEqual([]);
  expect(seenRequests.filter(isChatPost).map(requestSummary)).toEqual([]);
  expect(seenRequests.filter(isConversationCreatePost).map(requestSummary)).toEqual([]);
  expect(seenRequests.filter((req) => !isLocalBrowserRequest(req)).map(requestSummary)).toEqual([]);
  expect(seenRequests.filter(isExecutionServiceRequest).map(requestSummary)).toEqual([]);
  expect(consoleErrors).toEqual([]);
  expect(pageErrors).toEqual([]);
});
