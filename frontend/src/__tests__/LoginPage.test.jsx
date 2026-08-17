import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock the API using vi.hoisted
const { mockLoginApi, mockRegisterApi, mockAuthLogin } = vi.hoisted(() => ({
  mockLoginApi: vi.fn(),
  mockRegisterApi: vi.fn(),
  mockAuthLogin: vi.fn(),
}));

vi.mock('@/api/auth', () => ({
  login: mockLoginApi,
  register: mockRegisterApi,
}));

// Mock useAuth
vi.mock('@/lib/AuthContext', () => ({
  useAuth: () => ({
    user: null,
    login: mockAuthLogin,
    logout: vi.fn(),
    loading: false,
    isAuthenticated: false,
  }),
  AuthProvider: ({ children }) => children,
}));

// Import after mocks
import LoginPage from '@/pages/LoginPage';

const renderLoginPage = () => {
  return render(
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <LoginPage />
    </BrowserRouter>
  );
};

describe('LoginPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.history.pushState({}, '', '/login');
  });

  const usernameLabel = '用户名';
  const passwordLabel = '密码';

  it('renders login form elements', () => {
    renderLoginPage();

    // "AgentX" appears in both the brand panel and the form heading
    expect(screen.getAllByText('AgentX').length).toBeGreaterThan(0);
    // Login mode uses username + password.
    expect(screen.getByLabelText(usernameLabel)).toBeInTheDocument();
    expect(screen.getByLabelText(passwordLabel)).toBeInTheDocument();
  });

  it('renders submit and guest buttons', () => {
    const { container } = renderLoginPage();

    // Submit button (登录) — also exists as Tab, so check via type
    expect(container.querySelector('button[type="submit"]')).toBeInTheDocument();
    // Guest / demo button
    expect(screen.getByText('以访客身份继续')).toBeInTheDocument();
  });

  it('links to terms and privacy policy pages', () => {
    renderLoginPage();

    expect(screen.getByRole('link', { name: '服务条款' })).toHaveAttribute(
      'href',
      '/terms'
    );
    expect(screen.getByRole('link', { name: '隐私政策' })).toHaveAttribute(
      'href',
      '/privacy'
    );
  });

  it('calls login API with username credentials on form submit', async () => {
    mockLoginApi.mockResolvedValue({
      access_token: 'test-token',
      refresh_token: 'test-refresh',
    });

    renderLoginPage();

    const usernameInput = screen.getByLabelText(usernameLabel);
    const passwordInput = screen.getByLabelText(passwordLabel);
    const form = usernameInput.closest('form');

    fireEvent.change(usernameInput, { target: { value: 'testuser' } });
    fireEvent.change(passwordInput, { target: { value: 'testpass123' } });
    fireEvent.submit(form);

    await waitFor(() => {
      expect(mockLoginApi).toHaveBeenCalledWith('testuser', 'testpass123');
    });
  });

  it('calls auth login on successful login', async () => {
    mockLoginApi.mockResolvedValue({
      access_token: 'test-token',
      refresh_token: 'test-refresh',
    });

    renderLoginPage();

    fireEvent.change(screen.getByLabelText(usernameLabel), {
      target: { value: 'testuser' },
    });
    fireEvent.change(screen.getByLabelText(passwordLabel), {
      target: { value: 'testpass123' },
    });
    fireEvent.submit(screen.getByLabelText(usernameLabel).closest('form'));

    await waitFor(() => {
      expect(mockAuthLogin).toHaveBeenCalledWith('test-token', 'test-refresh');
    });
  });

  it('displays error message on login failure', async () => {
    mockLoginApi.mockRejectedValue({
      response: { data: { detail: 'Incorrect username or password' } },
    });

    renderLoginPage();

    fireEvent.change(screen.getByLabelText(usernameLabel), {
      target: { value: 'wronguser' },
    });
    fireEvent.change(screen.getByLabelText(passwordLabel), {
      target: { value: 'wrongpass123' },
    });
    fireEvent.submit(screen.getByLabelText(usernameLabel).closest('form'));

    await waitFor(() => {
      expect(screen.getByText('用户名或密码错误，请检查后重试')).toBeInTheDocument();
    });
  });

  it('does not expose raw axios status text on login failure', async () => {
    mockLoginApi.mockRejectedValue({
      response: { status: 401, data: {} },
      message: 'Request failed with status code 401',
    });

    renderLoginPage();

    fireEvent.change(screen.getByLabelText(usernameLabel), {
      target: { value: 'testuser' },
    });
    fireEvent.change(screen.getByLabelText(passwordLabel), {
      target: { value: 'testpass123' },
    });
    fireEvent.submit(screen.getByLabelText(usernameLabel).closest('form'));

    await waitFor(() => {
      expect(screen.getByText('用户名或密码错误，请检查后重试')).toBeInTheDocument();
      expect(screen.queryByText('Request failed with status code 401')).not.toBeInTheDocument();
    });
  });

  it('shows error when no access token returned', async () => {
    mockLoginApi.mockResolvedValue({});

    renderLoginPage();

    fireEvent.change(screen.getByLabelText(usernameLabel), {
      target: { value: 'testuser' },
    });
    fireEvent.change(screen.getByLabelText(passwordLabel), {
      target: { value: 'testpass123' },
    });
    fireEvent.submit(screen.getByLabelText(usernameLabel).closest('form'));

    await waitFor(() => {
      expect(screen.getByText('未获取到有效的访问令牌')).toBeInTheDocument();
    });
  });

  it('calls demo login API on guest button click', async () => {
    mockLoginApi.mockResolvedValue({
      access_token: 'demo-token',
      refresh_token: 'demo-refresh',
    });

    renderLoginPage();

    fireEvent.click(screen.getByText('以访客身份继续'));

    await waitFor(() => {
      expect(mockLoginApi).toHaveBeenCalledWith('demo', 'demo123456');
    });
  });

  it('does not call API when username is empty', async () => {
    renderLoginPage();

    const form = screen.getByLabelText(usernameLabel).closest('form');
    fireEvent.submit(form);

    await waitFor(() => {
      expect(mockLoginApi).not.toHaveBeenCalled();
    });
  });

  it('does not call API when password is too short', async () => {
    renderLoginPage();

    fireEvent.change(screen.getByLabelText(usernameLabel), {
      target: { value: 'testuser' },
    });
    fireEvent.change(screen.getByLabelText(passwordLabel), {
      target: { value: '123' },
    });
    fireEvent.submit(screen.getByLabelText(usernameLabel).closest('form'));

    await waitFor(() => {
      expect(mockLoginApi).not.toHaveBeenCalled();
    });
  });

  it('requires 8 characters before submitting registration to match backend policy', async () => {
    renderLoginPage();

    fireEvent.click(screen.getByRole('tab', { name: '注册' }));
    fireEvent.change(screen.getByLabelText('用户名'), {
      target: { value: 'newuser' },
    });
    fireEvent.change(screen.getByLabelText('邮箱'), {
      target: { value: 'newuser@example.com' },
    });
    fireEvent.change(screen.getByLabelText(passwordLabel), {
      target: { value: '1234567' },
    });
    fireEvent.submit(screen.getByLabelText('邮箱').closest('form'));

    expect(await screen.findByText('密码长度至少为 8 位')).toBeInTheDocument();
    expect(mockRegisterApi).not.toHaveBeenCalled();
  });

  it('sends new registrations to the setup checklist before chat', async () => {
    mockRegisterApi.mockResolvedValue({});
    mockLoginApi.mockResolvedValue({
      access_token: 'new-user-token',
      refresh_token: 'new-user-refresh',
    });

    renderLoginPage();

    fireEvent.click(screen.getByRole('tab', { name: '注册' }));
    fireEvent.change(screen.getByLabelText('用户名'), {
      target: { value: 'newuser' },
    });
    fireEvent.change(screen.getByLabelText('邮箱'), {
      target: { value: 'newuser@example.com' },
    });
    fireEvent.change(screen.getByLabelText(passwordLabel), {
      target: { value: '12345678' },
    });
    fireEvent.submit(screen.getByLabelText('邮箱').closest('form'));

    await waitFor(() => {
      expect(mockRegisterApi).toHaveBeenCalledWith({
        username: 'newuser',
        password: '12345678',
        email: 'newuser@example.com',
        company_name: 'newuser 的工作区',
        brand_name: 'newuser',
        category: '其他',
      });
      expect(mockLoginApi).toHaveBeenCalledWith('newuser', '12345678');
      expect(window.location.pathname).toBe('/settings');
    });
  });

  it('does not expose raw axios status text on registration server errors', async () => {
    mockRegisterApi.mockRejectedValue({
      response: { status: 500, data: {} },
      message: 'Request failed with status code 500',
    });

    renderLoginPage();

    fireEvent.click(screen.getByRole('tab', { name: '注册' }));
    fireEvent.change(screen.getByLabelText('用户名'), {
      target: { value: 'newuser' },
    });
    fireEvent.change(screen.getByLabelText('邮箱'), {
      target: { value: 'newuser@example.com' },
    });
    fireEvent.change(screen.getByLabelText(passwordLabel), {
      target: { value: '12345678' },
    });
    fireEvent.submit(screen.getByLabelText('邮箱').closest('form'));

    await waitFor(() => {
      expect(screen.getByText('注册服务暂时不可用，请稍后重试')).toBeInTheDocument();
      expect(screen.queryByText('Request failed with status code 500')).not.toBeInTheDocument();
    });
  });
});
