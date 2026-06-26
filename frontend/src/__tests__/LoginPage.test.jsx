import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock the API using vi.hoisted
const { mockLoginApi, mockAuthLogin } = vi.hoisted(() => ({
  mockLoginApi: vi.fn(),
  mockAuthLogin: vi.fn(),
}));

vi.mock('@/api/auth', () => ({
  login: mockLoginApi,
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

    expect(screen.getByText('AgentX')).toBeInTheDocument();
    expect(screen.getByText('AI 工作助手 — 对话即可完成工作')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('请输入用户名')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('请输入密码')).toBeInTheDocument();
  });

  it('renders login and demo buttons', () => {
    renderLoginPage();

    expect(screen.getByText('登 录')).toBeInTheDocument();
    expect(screen.getByText('演示账号登录')).toBeInTheDocument();
  });

  it('calls login API with correct credentials on form submit', async () => {
    mockLoginApi.mockResolvedValue({
      access_token: 'test-token',
      refresh_token: 'test-refresh',
    });

    renderLoginPage();

    const usernameInput = screen.getByPlaceholderText('请输入用户名');
    const passwordInput = screen.getByPlaceholderText('请输入密码');
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

    fireEvent.change(screen.getByPlaceholderText('请输入用户名'), {
      target: { value: 'testuser' },
    });
    fireEvent.change(screen.getByPlaceholderText('请输入密码'), {
      target: { value: 'testpass123' },
    });
    fireEvent.submit(screen.getByPlaceholderText('请输入用户名').closest('form'));

    await waitFor(() => {
      expect(mockAuthLogin).toHaveBeenCalledWith('test-token', 'test-refresh');
    });
  });

  it('displays error message on login failure', async () => {
    mockLoginApi.mockRejectedValue({
      response: { data: { detail: 'Incorrect username or password' } },
    });

    renderLoginPage();

    fireEvent.change(screen.getByPlaceholderText('请输入用户名'), {
      target: { value: 'wronguser' },
    });
    fireEvent.change(screen.getByPlaceholderText('请输入密码'), {
      target: { value: 'wrongpass123' },
    });
    fireEvent.submit(screen.getByPlaceholderText('请输入用户名').closest('form'));

    await waitFor(() => {
      expect(screen.getByText('用户名或密码错误')).toBeInTheDocument();
    });
  });

  it('displays generic error when no detail in response', async () => {
    mockLoginApi.mockRejectedValue(new Error('Network error'));

    renderLoginPage();

    fireEvent.change(screen.getByPlaceholderText('请输入用户名'), {
      target: { value: 'testuser' },
    });
    fireEvent.change(screen.getByPlaceholderText('请输入密码'), {
      target: { value: 'testpass123' },
    });
    fireEvent.submit(screen.getByPlaceholderText('请输入用户名').closest('form'));

    await waitFor(() => {
      expect(screen.getByText('Network error')).toBeInTheDocument();
    });
  });

  it('shows error when no access token returned', async () => {
    mockLoginApi.mockResolvedValue({});

    renderLoginPage();

    fireEvent.change(screen.getByPlaceholderText('请输入用户名'), {
      target: { value: 'testuser' },
    });
    fireEvent.change(screen.getByPlaceholderText('请输入密码'), {
      target: { value: 'testpass123' },
    });
    fireEvent.submit(screen.getByPlaceholderText('请输入用户名').closest('form'));

    await waitFor(() => {
      expect(screen.getByText('未获取到有效的访问令牌')).toBeInTheDocument();
    });
  });

  it('calls demo login API on demo button click', async () => {
    mockLoginApi.mockResolvedValue({
      access_token: 'demo-token',
      refresh_token: 'demo-refresh',
    });

    renderLoginPage();

    fireEvent.click(screen.getByText('演示账号登录'));

    await waitFor(() => {
      expect(mockLoginApi).toHaveBeenCalledWith('demo', 'demo123456');
    });
  });

  it('does not call API when username is empty', async () => {
    renderLoginPage();

    const form = screen.getByPlaceholderText('请输入用户名').closest('form');
    fireEvent.submit(form);

    await waitFor(() => {
      expect(mockLoginApi).not.toHaveBeenCalled();
    });
  });

  it('does not call API when password is too short', async () => {
    renderLoginPage();

    fireEvent.change(screen.getByPlaceholderText('请输入用户名'), {
      target: { value: 'testuser' },
    });
    fireEvent.change(screen.getByPlaceholderText('请输入密码'), {
      target: { value: '123' },
    });
    fireEvent.submit(screen.getByPlaceholderText('请输入用户名').closest('form'));

    await waitFor(() => {
      expect(mockLoginApi).not.toHaveBeenCalled();
    });
  });
});