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

function normalizedPath(request) {
  const url = parseRequestUrl(request);
  return url ? url.pathname.replace(/\/+$/, '') : '';
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
  return request.method() === 'POST' && normalizedPath(request) === '/api/chat';
}

function isConversationCreatePost(request) {
  return request.method() === 'POST' && normalizedPath(request) === '/api/conversations';
}

function isConversationDetailGet(request, id) {
  return (
    request.method() === 'GET' &&
    normalizedPath(request) === `/api/conversations/${id}`
  );
}

function isConversationDelete(request) {
  return (
    request.method() === 'DELETE' &&
    normalizedPath(request).startsWith('/api/conversations/')
  );
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
    'agent-runtime',
    'agentruntime',
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
  await page.goto(`${FRONTEND_URL}/login`, { waitUntil: 'domcontentloaded' });
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

test('public-demo lightweight conversations stay read-only until explicit chat send or confirmed delete', async ({ page, request }) => {
  const seenRequests = [];
  const blockedChatRequests = [];
  const blockedConversationCreates = [];
  const blockedConversationDeletes = [];
  const blockedExecutionRequests = [];
  const blockedExternalRequests = [];
  const detailRequests = [];
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
    if (isConversationDelete(browserRequest)) {
      blockedConversationDeletes.push(browserRequest);
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

  const suffix = `${Date.now()}${Math.random().toString(36).slice(2, 8)}`;
  const username = `smokeconv${suffix}`;
  const password = `LocalConv${suffix}!`;
  const email = `agentx-smoke-conv-${suffix}@example.test`;

  await registerSmokeUser(request, { username, email, password });

  const emptyConversationsResponse = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return (
      url.pathname === '/api/conversations' &&
      url.searchParams.get('limit') === '50' &&
      response.request().method() === 'GET'
    );
  });

  await loginThroughFrontend(page, { username, password });
  collectPageErrors = true;

  const emptyConversations = await emptyConversationsResponse;
  expect(emptyConversations.status()).toBe(200);
  const emptyConversationsBody = await emptyConversations.json();
  expect(emptyConversationsBody.total).toBe(0);
  expect(emptyConversationsBody.items).toEqual([]);

  await expect(page).toHaveURL(`${FRONTEND_URL}/`);
  await expect(page.locator('aside')).toBeVisible();
  await expect(page.getByText(/\u8fd8\u6ca1\u6709\u5bf9\u8bdd/)).toBeVisible();

  const newChatButton = page.getByRole('button', { name: /\u65b0\u5efa\u5bf9\u8bdd|\u65b0\u5bf9\u8bdd/ }).first();
  await expect(newChatButton).toBeVisible();
  await newChatButton.click();
  await page.waitForTimeout(500);
  expect(blockedConversationCreates.map(requestSummary)).toEqual([]);
  expect(blockedChatRequests.map(requestSummary)).toEqual([]);

  const title = `History Smoke ${suffix}`;
  const createResponse = await page.request.post(`${FRONTEND_URL}/api/conversations`, {
    data: { title },
  });
  expect(createResponse.status(), await createResponse.text()).toBe(201);
  const createdConversation = await createResponse.json();
  expect(createdConversation.title).toBe(title);

  const refreshedConversationsResponse = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return (
      url.pathname === '/api/conversations' &&
      url.searchParams.get('limit') === '50' &&
      response.request().method() === 'GET'
    );
  });
  await page.reload({ waitUntil: 'domcontentloaded' });
  expect((await refreshedConversationsResponse).status()).toBe(200);

  const conversationButton = page.getByRole('button', { name: new RegExp(title) }).first();
  await expect(conversationButton).toBeVisible();

  const detailResponsePromise = page.waitForResponse((response) => {
    const req = response.request();
    if (isConversationDetailGet(req, createdConversation.id)) {
      detailRequests.push(req);
      return true;
    }
    return false;
  });
  await conversationButton.click();
  const detailResponse = await detailResponsePromise;
  expect(detailResponse.status()).toBe(200);
  expect(detailRequests.map(requestSummary)).toEqual([
    `GET http://localhost:3000/api/conversations/${createdConversation.id}`,
  ]);

  await conversationButton.hover();
  const deleteControl = page.locator(`[aria-label*="${title}"]`).first();
  await expect(deleteControl).toBeVisible();

  const confirmDismissed = page.waitForEvent('dialog').then(async (dialog) => {
    expect(dialog.type()).toBe('confirm');
    await dialog.dismiss();
    return true;
  });
  await deleteControl.click();
  expect(await confirmDismissed).toBe(true);
  await page.waitForTimeout(500);

  expect(blockedChatRequests.map(requestSummary)).toEqual([]);
  expect(blockedConversationCreates.map(requestSummary)).toEqual([]);
  expect(blockedConversationDeletes.map(requestSummary)).toEqual([]);
  expect(blockedExecutionRequests.map(requestSummary)).toEqual([]);
  expect(blockedExternalRequests.map(requestSummary)).toEqual([]);
  expect(seenRequests.filter(isChatPost).map(requestSummary)).toEqual([]);
  expect(seenRequests.filter(isConversationCreatePost).map(requestSummary)).toEqual([]);
  expect(seenRequests.filter(isConversationDelete).map(requestSummary)).toEqual([]);
  expect(seenRequests.filter((req) => !isLocalBrowserRequest(req)).map(requestSummary)).toEqual([]);
  expect(seenRequests.filter(isExecutionServiceRequest).map(requestSummary)).toEqual([]);
  expect(consoleErrors).toEqual([]);
  expect(pageErrors).toEqual([]);
});
