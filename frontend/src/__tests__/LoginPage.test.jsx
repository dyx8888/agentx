import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock the API using vi.hoisted
const { mockLoginApi, mockAuthLogin, mockAuthSetUser } = vi.hoisted(() => ({
  mockLoginApi: vi.fn(),
  mockAuthLogin: vi.fn(),
  mockAuthSetUser: vi.fn(),
}));

vi.mock('@/api/auth', () => ({
  login: mockLoginApi,
}));

// Mock useAuth
vi.mock('@/lib/AuthContext', () => ({
  useAuth: () => ({
    user: null,
    setUser: mockAuthSetUser,
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
    <BrowserRouter>
      <LoginPage />
    </BrowserRouter>
  );
};

describe('LoginPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders login form elements', () => {
    renderLoginPage();

    expect(screen.getByText('欢迎回来')).toBeInTheDocument();
    expect(screen.getByText('请输入您的账号信息登录系统')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('用户名')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('密码')).toBeInTheDocument();
    expect(screen.getByText('AgentX')).toBeInTheDocument();
  });

  it('renders demo login button', () => {
    renderLoginPage();

    expect(screen.getByText('演示账号登录')).toBeInTheDocument();
  });

  it('renders brand panel content', () => {
    renderLoginPage();

    expect(screen.getByText('已有超过 10,000+ 企业信赖我们')).toBeInTheDocument();
  });

  it('calls login API with correct credentials on form submit', async () => {
    mockLoginApi.mockResolvedValue({
      access_token: 'test-token',
      refresh_token: 'test-refresh',
      user: { id: 1, username: 'testuser' },
    });

    renderLoginPage();

    const usernameInput = screen.getByPlaceholderText('用户名');
    const passwordInput = screen.getByPlaceholderText('密码');
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
      user: { id: 1, username: 'testuser' },
    });

    renderLoginPage();

    fireEvent.change(screen.getByPlaceholderText('用户名'), {
      target: { value: 'testuser' },
    });
    fireEvent.change(screen.getByPlaceholderText('密码'), {
      target: { value: 'testpass123' },
    });
    fireEvent.submit(screen.getByPlaceholderText('用户名').closest('form'));

    await waitFor(() => {
      expect(mockAuthLogin).toHaveBeenCalledWith('test-token', 'test-refresh');
      expect(mockAuthSetUser).toHaveBeenCalledWith({ id: 1, username: 'testuser' });
    });
  });

  it('displays error message on login failure', async () => {
    mockLoginApi.mockRejectedValue({
      response: { data: { detail: 'Incorrect username or password' } },
    });

    renderLoginPage();

    fireEvent.change(screen.getByPlaceholderText('用户名'), {
      target: { value: 'wronguser' },
    });
    fireEvent.change(screen.getByPlaceholderText('密码'), {
      target: { value: 'wrongpass123' },
    });
    fireEvent.submit(screen.getByPlaceholderText('用户名').closest('form'));

    await waitFor(() => {
      expect(screen.getByText('用户名或密码错误')).toBeInTheDocument();
    });
  });

  it('displays generic error when no detail in response', async () => {
    mockLoginApi.mockRejectedValue(new Error('Network error'));

    renderLoginPage();

    fireEvent.change(screen.getByPlaceholderText('用户名'), {
      target: { value: 'testuser' },
    });
    fireEvent.change(screen.getByPlaceholderText('密码'), {
      target: { value: 'testpass123' },
    });
    fireEvent.submit(screen.getByPlaceholderText('用户名').closest('form'));

    await waitFor(() => {
      expect(screen.getByText('Network error')).toBeInTheDocument();
    });
  });

  it('shows error when no access token returned', async () => {
    mockLoginApi.mockResolvedValue({});

    renderLoginPage();

    fireEvent.change(screen.getByPlaceholderText('用户名'), {
      target: { value: 'testuser' },
    });
    fireEvent.change(screen.getByPlaceholderText('密码'), {
      target: { value: 'testpass123' },
    });
    fireEvent.submit(screen.getByPlaceholderText('用户名').closest('form'));

    await waitFor(() => {
      expect(screen.getByText('未获取到有效的访问令牌')).toBeInTheDocument();
    });
  });

  it('calls demo login API on demo button click', async () => {
    mockLoginApi.mockResolvedValue({
      access_token: 'demo-token',
      refresh_token: 'demo-refresh',
      user: { id: 0, username: 'demo' },
    });

    renderLoginPage();

    fireEvent.click(screen.getByText('演示账号登录'));

    await waitFor(() => {
      expect(mockLoginApi).toHaveBeenCalledWith('demo', 'demo123456');
    });
  });

  it('does not call API when username is empty', async () => {
    renderLoginPage();

    const form = screen.getByPlaceholderText('用户名').closest('form');
    fireEvent.submit(form);

    await waitFor(() => {
      expect(mockLoginApi).not.toHaveBeenCalled();
    });
  });

  it('does not call API when password is too short', async () => {
    renderLoginPage();

    fireEvent.change(screen.getByPlaceholderText('用户名'), {
      target: { value: 'testuser' },
    });
    fireEvent.change(screen.getByPlaceholderText('密码'), {
      target: { value: '123' },
    });
    fireEvent.submit(screen.getByPlaceholderText('用户名').closest('form'));

    await waitFor(() => {
      expect(mockLoginApi).not.toHaveBeenCalled();
    });
  });
});