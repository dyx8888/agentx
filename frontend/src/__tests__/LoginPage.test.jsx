import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock the API using vi.hoisted
const {
  mockLoginApi,
  mockRegisterApi,
  mockVerifyEmailCode,
  mockResendEmailCode,
  mockAuthLogin,
} = vi.hoisted(() => ({
  mockLoginApi: vi.fn(),
  mockRegisterApi: vi.fn(),
  mockVerifyEmailCode: vi.fn(),
  mockResendEmailCode: vi.fn(),
  mockAuthLogin: vi.fn(),
}));

vi.mock('@/api/auth', () => ({
  login: mockLoginApi,
  register: mockRegisterApi,
  verifyEmailCode: mockVerifyEmailCode,
  resendEmailCode: mockResendEmailCode,
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
    vi.stubEnv('VITE_PUBLIC_REGISTRATION_ENABLED', 'false');
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

  it('hides public registration entry by default while keeping password recovery', () => {
    renderLoginPage();

    expect(screen.queryByRole('tab', { name: '注册' })).not.toBeInTheDocument();
    expect(screen.getByRole('tab', { name: '登录' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '忘记密码？' })).toHaveAttribute(
      'href',
      '/forgot-password'
    );
  });

  it('does not call registration API from the public login form', async () => {
    mockLoginApi.mockResolvedValue({
      access_token: 'login-token',
      refresh_token: 'login-refresh',
    });

    renderLoginPage();

    fireEvent.change(screen.getByLabelText('用户名'), {
      target: { value: 'testuser' },
    });
    fireEvent.change(screen.getByLabelText(passwordLabel), {
      target: { value: 'testpass123' },
    });
    fireEvent.submit(screen.getByLabelText('用户名').closest('form'));

    await waitFor(() => {
      expect(mockLoginApi).toHaveBeenCalledWith('testuser', 'testpass123');
    });
    expect(mockRegisterApi).not.toHaveBeenCalled();
  });

  it('shows email code verification after enabled public registration succeeds', async () => {
    vi.stubEnv('VITE_PUBLIC_REGISTRATION_ENABLED', 'true');
    mockRegisterApi.mockResolvedValue({
      email_verification_required: true,
      masked_email: 'ne***@example.com',
      message: '验证码已发送，请查收邮箱并完成验证',
    });

    renderLoginPage();

    fireEvent.click(screen.getByRole('tab', { name: '注册' }));
    fireEvent.change(screen.getByLabelText('用户名'), {
      target: { value: 'newuser' },
    });
    fireEvent.change(screen.getByLabelText('邮箱'), {
      target: { value: 'new@example.com' },
    });
    fireEvent.change(screen.getByLabelText(passwordLabel), {
      target: { value: 'password123' },
    });
    fireEvent.submit(screen.getByLabelText('邮箱').closest('form'));

    await waitFor(() => {
      expect(mockRegisterApi).toHaveBeenCalledWith({
        username: 'newuser',
        password: 'password123',
        email: 'new@example.com',
        company_name: 'newuser 的工作区',
        brand_name: 'newuser',
        category: '其他',
      });
    });
    expect(await screen.findByLabelText('邮箱验证码')).toBeInTheDocument();
    expect(screen.getByText(/ne\*\*\*@example\.com/)).toBeInTheDocument();
    expect(mockLoginApi).not.toHaveBeenCalled();
    expect(mockAuthLogin).not.toHaveBeenCalled();
  });

  it('verifies email code and returns to login without auto-login', async () => {
    vi.stubEnv('VITE_PUBLIC_REGISTRATION_ENABLED', 'true');
    mockRegisterApi.mockResolvedValue({
      email_verification_required: true,
      masked_email: 'ne***@example.com',
      message: '验证码已发送，请查收邮箱并完成验证',
    });
    mockVerifyEmailCode.mockResolvedValue({ success: true, message: '邮箱已验证' });

    renderLoginPage();

    fireEvent.click(screen.getByRole('tab', { name: '注册' }));
    fireEvent.change(screen.getByLabelText('用户名'), {
      target: { value: 'newuser' },
    });
    fireEvent.change(screen.getByLabelText('邮箱'), {
      target: { value: 'new@example.com' },
    });
    fireEvent.change(screen.getByLabelText(passwordLabel), {
      target: { value: 'password123' },
    });
    fireEvent.submit(screen.getByLabelText('邮箱').closest('form'));

    const codeInput = await screen.findByLabelText('邮箱验证码');
    fireEvent.change(codeInput, { target: { value: '123456' } });
    fireEvent.submit(codeInput.closest('form'));

    await waitFor(() => {
      expect(mockVerifyEmailCode).toHaveBeenCalledWith({
        email: 'new@example.com',
        username: 'newuser',
        code: '123456',
      });
    });
    expect(screen.getByText('邮箱已验证，请登录')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: '登录' })).toHaveAttribute(
      'aria-selected',
      'true'
    );
    expect(mockLoginApi).not.toHaveBeenCalled();
  });

  it('resends email verification code from the verification step', async () => {
    vi.stubEnv('VITE_PUBLIC_REGISTRATION_ENABLED', 'true');
    mockRegisterApi.mockResolvedValue({
      email_verification_required: true,
      masked_email: 'ne***@example.com',
      message: '验证码已发送，请查收邮箱并完成验证',
    });
    mockResendEmailCode.mockResolvedValue({
      success: true,
      message: '如果账户需要验证，验证码已重新发送',
    });

    renderLoginPage();

    fireEvent.click(screen.getByRole('tab', { name: '注册' }));
    fireEvent.change(screen.getByLabelText('用户名'), {
      target: { value: 'newuser' },
    });
    fireEvent.change(screen.getByLabelText('邮箱'), {
      target: { value: 'new@example.com' },
    });
    fireEvent.change(screen.getByLabelText(passwordLabel), {
      target: { value: 'password123' },
    });
    fireEvent.submit(screen.getByLabelText('邮箱').closest('form'));

    await screen.findByLabelText('邮箱验证码');
    fireEvent.click(screen.getByRole('button', { name: '重新发送验证码' }));

    await waitFor(() => {
      expect(mockResendEmailCode).toHaveBeenCalledWith({
        email: 'new@example.com',
        username: 'newuser',
      });
    });
    expect(screen.getByText('如果账户需要验证，验证码已重新发送')).toBeInTheDocument();
  });

  it('does not enter verification step when registration fails', async () => {
    vi.stubEnv('VITE_PUBLIC_REGISTRATION_ENABLED', 'true');
    mockRegisterApi.mockRejectedValue({
      response: { data: { detail: 'Username already registered' } },
    });

    renderLoginPage();

    fireEvent.click(screen.getByRole('tab', { name: '注册' }));
    fireEvent.change(screen.getByLabelText('用户名'), {
      target: { value: 'newuser' },
    });
    fireEvent.change(screen.getByLabelText('邮箱'), {
      target: { value: 'new@example.com' },
    });
    fireEvent.change(screen.getByLabelText(passwordLabel), {
      target: { value: 'password123' },
    });
    fireEvent.submit(screen.getByLabelText('邮箱').closest('form'));

    await waitFor(() => {
      expect(screen.getByText('用户名已被注册，请更换用户名或直接登录')).toBeInTheDocument();
    });
    expect(screen.queryByLabelText('邮箱验证码')).not.toBeInTheDocument();
  });
});
