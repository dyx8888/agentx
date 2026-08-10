import { test, expect } from '@playwright/test';

const BASE_URL = 'http://localhost:5173';

// ============================================================
// 辅助函数: 登录 + Mock API
// 注意: 在页面加载后再设置 mock，避免影响页面渲染
// 不要拦截 /api/auth/me！LoginPage 通过 setUser() 直接设置用户
// ============================================================
async function loginUser(page) {
  await page.goto(`${BASE_URL}/login`);
  await page.waitForLoadState('networkidle');
  await expect(page.getByPlaceholder('用户名')).toBeVisible({ timeout: 5000 });

  // 设置 mock（页面加载后再设置，避免影响页面渲染）
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

  await page.route(/\/api\/conversations/, async (route) => {
    const method = route.request().method();
    if (method === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          items: [{ id: 'c1', title: 'Test', updated_at: new Date().toISOString() }],
        }),
      });
    } else if (method === 'DELETE') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '{"ok":true}' });
    } else {
      await route.continue();
    }
  });

  await page.getByPlaceholder('用户名').fill('testuser');
  await page.getByPlaceholder('密码').fill('testpass123');
  await page.locator('button[type="submit"]').first().click();
  await page.waitForURL('**/chat', { timeout: 15000 });
  await page.waitForTimeout(2000);
}

// ============================================================
// 测试套件 1: 登录流程
// ============================================================
test.describe('登录流程', () => {
  test('页面加载 - 显示登录表单', async ({ page }) => {
    await page.goto(`${BASE_URL}/login`);
    await page.waitForLoadState('networkidle');

    // 验证品牌面板
    await expect(page.getByText('AgentX')).toBeVisible();
    await expect(page.getByText('数字员工')).toBeVisible();
    await expect(page.getByText('已有超过 10,000+ 企业信赖我们')).toBeVisible();

    // 验证登录表单
    await expect(page.getByText('欢迎回来')).toBeVisible();
    await expect(page.getByPlaceholder('用户名')).toBeVisible();
    await expect(page.getByPlaceholder('密码')).toBeVisible();
    await expect(page.getByText('演示账号登录')).toBeVisible();
  });

  test('表单验证 - 空用户名提交', async ({ page }) => {
    await page.goto(`${BASE_URL}/login`);
    await page.waitForLoadState('networkidle');

    const submitBtn = page.locator('button[type="submit"]').first();
    await submitBtn.click();

    await expect(page.getByText('请输入用户名')).toBeVisible();
  });

  test('表单验证 - 密码太短', async ({ page }) => {
    await page.goto(`${BASE_URL}/login`);
    await page.waitForLoadState('networkidle');

    await page.getByPlaceholder('用户名').fill('testuser');
    await page.getByPlaceholder('密码').fill('123');

    const submitBtn = page.locator('button[type="submit"]').first();
    await submitBtn.click();

    await expect(page.getByText('密码至少 8 位')).toBeVisible();
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
    await expect(page.getByPlaceholder('用户名')).toBeVisible({ timeout: 5000 });
  });
});

// ============================================================
// 测试套件 3: Mock 登录 API 流程
// 注意: 不要拦截 /api/auth/me！LoginPage 通过 setUser() 直接设置用户，
// 拦截 /api/auth/me 会导致 AuthContext 误认为已登录而提前跳转
// ============================================================
test.describe('Mock 登录 API', () => {
  test('Mock 登录成功跳转到聊天页', async ({ page }) => {
    // 先导航到登录页，确认页面加载正常
    await page.goto(`${BASE_URL}/login`);
    await page.waitForLoadState('networkidle');

    // 确认登录表单存在
    await expect(page.getByPlaceholder('用户名')).toBeVisible({ timeout: 5000 });

    // 然后设置 mock（在导航后设置，避免影响页面加载）
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

    await page.route(/\/api\/conversations/, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items: [] }),
      });
    });

    // 填写表单
    await page.getByPlaceholder('用户名').fill('testuser');
    await page.getByPlaceholder('密码').fill('testpass123');

    // 提交
    await page.locator('button[type="submit"]').first().click();

    // 等待跳转
    await page.waitForURL('**/chat', { timeout: 15000 });
    await page.waitForTimeout(2000);

    // 验证在聊天页
    await expect(page.locator('text=新对话').first()).toBeVisible({ timeout: 5000 });
  });
});

// ============================================================
// 测试套件 4: 对话管理 Mock API 流程
// ============================================================
test.describe('对话管理 Mock API', () => {
  test('新建对话', async ({ page }) => {
    await loginUser(page);

    await page.getByTestId('new-chat-btn').click();
    await page.waitForTimeout(500);

    await expect(page.getByTestId('message-count')).toHaveText('0', { timeout: 5000 });
  });

  test('发送消息', async ({ page }) => {
    await loginUser(page);

    // 在聊天输入框中输入消息
    const input = page.getByTestId('chat-input');
    await expect(input).toBeVisible({ timeout: 5000 });
    await input.fill('测试消息');
    await page.getByTestId('send-btn').click();
    await page.waitForTimeout(500);

    // 验证消息已发送（输入框清空，消息计数增加）
    await expect(input).toHaveValue('');
    await expect(page.getByTestId('message-count')).not.toHaveText('0', { timeout: 5000 });
  });
});