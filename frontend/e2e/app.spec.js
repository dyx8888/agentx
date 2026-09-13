import { test, expect } from '@playwright/test';

const BASE_URL = 'http://localhost:5173';

// ============================================================
// 辅助函数: 登录 + Mock API
// 注意: 在页面加载后再设置 mock，避免影响页面渲染
// 不要拦截 /api/auth/me！LoginPage 通过 setUser() 直接设置用户
// ============================================================
async function mockAuxiliaryApi(page) {
  await page.route('**/*', async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (!pathname.startsWith('/api/')) {
      await route.fallback();
      return;
    }

    const handledBySpecificMock =
      pathname === '/api/auth/token' ||
      pathname === '/api/auth/users/me' ||
      pathname === '/api/chat' ||
      pathname === '/api/conversations' ||
      pathname.startsWith('/api/conversations/') ||
      pathname.startsWith('/api/browser-connector/capture-jobs');

    if (handledBySpecificMock) {
      await route.fallback();
      return;
    }

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: '{}',
    });
  });
}

async function loginUser(page) {
  // ChatPage requests several protected auxiliary resources on startup. Keep
  // this UI-only test deterministic while allowing specific mocks below to run.
  await mockAuxiliaryApi(page);

  // 先注册 mock，避免 AuthProvider 初始 getMe 请求触发本地后端重试。
  await page.route('**/api/auth/token', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        access_token: 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjk5OTk5OTk5OTksInN1YiI6InRlc3R1c2VyIn0.fake',
        refresh_token: 'mock-refresh',
        user: { id: 1, username: 'testuser' },
      }),
    });
  });

  await page.route('**/api/auth/users/me', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ id: 1, username: 'testuser', company_id: 1 }),
    });
  });

    await page.route(/\/api\/conversations(?:\?.*)?$/, async (route) => {
    const method = route.request().method();
    if (method === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: [{ id: 'c1', title: 'Test', updated_at: new Date().toISOString() }],
        }),
      });
    } else if (method === 'POST') {
      await route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({ id: 'c-new', title: '测试消息' }),
      });
    } else if (method === 'DELETE') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '{"ok":true}' });
    } else {
      await route.continue();
    }
  });

  await page.route('**/api/browser-connector/capture-jobs**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ items: [] }),
    });
  });

  await page.route('**/api/chat', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: 'data: {"type":"content","content":"测试回复"}\n\ndata: {"type":"done"}\n\ndata: [DONE]\n\n',
    });
  });

  await page.goto(`${BASE_URL}/`);
  await expect(page.getByRole('textbox', { name: '消息输入框' })).toBeVisible({
    timeout: 15000,
  });
}

// ============================================================
// 测试套件 1: 登录流程
// ============================================================
test.describe('登录流程', () => {
  test('页面加载 - 显示登录表单', async ({ page }) => {
    await page.goto(`${BASE_URL}/login`);
    await page.waitForLoadState('networkidle');

    // 验证品牌面板
    await expect(page.getByRole('heading', { name: 'AgentX', exact: true })).toBeVisible();
    await expect(page.getByRole('heading', { name: '用真实数据驱动电商运营对话' })).toBeVisible();
    await expect(page.getByText('达人搜索与建联')).toBeVisible();

    // 验证登录表单
    await expect(page.getByText('欢迎回来')).toBeVisible();
    await expect(page.locator('#email')).toBeVisible();
    await expect(page.locator('#password')).toBeVisible();
    await expect(page.getByRole('tab', { name: '登录' })).toBeVisible();
  });

  test('表单验证 - 空用户名提交', async ({ page }) => {
    await page.goto(`${BASE_URL}/login`);
    await page.waitForLoadState('networkidle');

    const submitBtn = page.locator('button[type="submit"]').first();
    await submitBtn.click();

    await expect(page.getByRole('alert')).toHaveText('请输入用户名');
  });

  test('表单验证 - 密码太短', async ({ page }) => {
    await page.goto(`${BASE_URL}/login`);
    await page.waitForLoadState('networkidle');

    await page.locator('#email').fill('testuser');
    await page.locator('#password').fill('123');

    const submitBtn = page.locator('button[type="submit"]').first();
    await submitBtn.click();

    await expect(page.getByRole('alert')).toHaveText('密码长度至少为 6 位');
  });
});

// ============================================================
// 测试套件 2: 未登录访问保护
// ============================================================
test.describe('路由保护', () => {
  test('未登录访问 /chat 重定向到 /login', async ({ page }) => {
    await page.goto(`${BASE_URL}/chat`);
    await page.waitForLoadState('networkidle');

    await expect(page.getByText('欢迎回来')).toBeVisible({ timeout: 5000 });
    await expect(page.locator('#email')).toBeVisible({ timeout: 5000 });
  });
});

// ============================================================
// 测试套件 3: Mock 登录 API 流程
// 注意: 不要拦截 /api/auth/me！LoginPage 通过 setUser() 直接设置用户，
// 拦截 /api/auth/me 会导致 AuthContext 误认为已登录而提前跳转
// ============================================================
test.describe('Mock 登录 API', () => {
  test('Mock 登录成功跳转到聊天页', async ({ page }) => {
    await mockAuxiliaryApi(page);
    let authenticated = false;

    // 先注册 mock，避免 AuthProvider 初始 getMe 请求触发本地后端重试。
    await page.route('**/api/auth/token', async (route) => {
      authenticated = true;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          access_token: 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjk5OTk5OTk5OTksInN1YiI6InRlc3R1c2VyIn0.fake',
          refresh_token: 'mock-refresh',
          user: { id: 1, username: 'testuser' },
        }),
      });
    });

    await page.route('**/api/auth/users/me', async (route) => {
      if (!authenticated) {
        await route.fulfill({
          status: 401,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'Not authenticated' }),
        });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ id: 1, username: 'testuser', company_id: 1 }),
      });
    });

  await page.route(/\/api\/conversations(?:\?.*)?$/, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items: [] }),
      });
    });

    await page.route('**/api/browser-connector/capture-jobs**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items: [] }),
      });
    });

    await page.goto(`${BASE_URL}/login`);
    await page.waitForLoadState('networkidle');
    await expect(page.locator('#email')).toBeVisible({ timeout: 5000 });

    // 填写表单
    await page.locator('#email').fill('testuser');
    await page.locator('#password').fill('testpass123');

    // 提交
    await page.locator('button[type="submit"]').first().click();

    // 等待跳转
    await page.waitForURL(`${BASE_URL}/`, { timeout: 15000 });
    await page.waitForTimeout(2000);

    // 验证在聊天页
    await expect(page.getByRole('heading', { name: '新对话' })).toBeVisible({ timeout: 5000 });
  });
});

// ============================================================
// 测试套件 4: 对话管理 Mock API 流程
// ============================================================
test.describe('对话管理 Mock API', () => {
  test('新建对话', async ({ page }) => {
    await loginUser(page);

    const input = page.getByRole('textbox', { name: '消息输入框' });
    await page.getByRole('button', { name: '新建对话' }).dispatchEvent('click');

    await expect(input).toHaveValue('', { timeout: 5000 });
    await expect(page.getByRole('button', { name: '发送' })).toBeDisabled();
  });

  test('发送消息', async ({ page }) => {
    await loginUser(page);

    // 在聊天输入框中输入消息
    const input = page.getByRole('textbox', { name: '消息输入框' });
    await expect(input).toBeVisible({ timeout: 5000 });
    await input.fill('测试消息');
    await page.getByRole('button', { name: '发送' }).click();
    await expect(page.getByText('测试回复')).toBeVisible({ timeout: 5000 });

    // 验证消息已发送（输入框清空，消息计数增加）
    await expect(input).toHaveValue('');
    await expect(page.getByText('测试消息')).toBeVisible({ timeout: 5000 });
  });
});
