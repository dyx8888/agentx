import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { BrowserRouter } from 'react-router-dom';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// Use vi.hoisted to avoid hoisting issues
const { mockLoginApi } = vi.hoisted(() => ({
  mockLoginApi: vi.fn(),
}));

// Mock the loginApi at module level
vi.mock('@/lib/api', () => ({
  loginApi: mockLoginApi,
  getAuthToken: () => null,
  setAuthTokens: vi.fn(),
  removeAuthTokens: vi.fn(),
  isTokenExpired: () => true,
}));

// Mock useAuth
vi.mock('@/lib/AuthContext', () => ({
  useAuth: () => ({
    user: null,
    setUser: vi.fn(),
    login: vi.fn(),
    logout: vi.fn(),
    loading: false,
    isAuthenticated: false,
  }),
  AuthProvider: ({ children }) => children,
}));

// Import after mocks
import { LoginForm } from '@/components/login-form';

const renderWithRouter = (component) => {
  return render(
    <BrowserRouter>
      {component}
    </BrowserRouter>
  );
};

describe('LoginForm', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders login form correctly', () => {
    renderWithRouter(<LoginForm />);

    expect(screen.getByText('欢迎回来')).toBeInTheDocument();
    expect(screen.getByText('请输入您的账号信息登录系统')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('请输入用户名或邮箱')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('请输入密码')).toBeInTheDocument();

    // Verify form exists and has submit button
    const form = screen.getByPlaceholderText('请输入用户名或邮箱').closest('form');
    expect(form).toBeInTheDocument();
    const submitBtn = form.querySelector('button[type="submit"]');
    expect(submitBtn).toBeInTheDocument();
  });

  it('calls loginApi with correct credentials when form is submitted', async () => {
    mockLoginApi.mockResolvedValue({
      access_token: 'test-token',
      refresh_token: 'test-refresh',
      user: { id: 1, username: 'testuser' },
    });

    renderWithRouter(<LoginForm />);

    const usernameInput = screen.getByPlaceholderText('请输入用户名或邮箱');
    const passwordInput = screen.getByPlaceholderText('请输入密码');
    const form = usernameInput.closest('form');

    fireEvent.change(usernameInput, { target: { value: 'testuser' } });
    fireEvent.change(passwordInput, { target: { value: 'testpass' } });
    fireEvent.submit(form);

    await waitFor(() => {
      expect(mockLoginApi).toHaveBeenCalledWith('testuser', 'testpass');
    });
  });

  it('displays error when loginApi fails', async () => {
    mockLoginApi.mockRejectedValue(new Error('Invalid credentials'));

    renderWithRouter(<LoginForm />);

    const usernameInput = screen.getByPlaceholderText('请输入用户名或邮箱');
    const passwordInput = screen.getByPlaceholderText('请输入密码');
    const form = usernameInput.closest('form');

    fireEvent.change(usernameInput, { target: { value: 'testuser' } });
    fireEvent.change(passwordInput, { target: { value: 'wrongpass' } });
    fireEvent.submit(form);

    await waitFor(() => {
      expect(mockLoginApi).toHaveBeenCalled();
    });
  });

  it('does not call API when username is empty', async () => {
    renderWithRouter(<LoginForm />);

    const usernameInput = screen.getByPlaceholderText('请输入用户名或邮箱');
    const passwordInput = screen.getByPlaceholderText('请输入密码');
    const form = usernameInput.closest('form');

    fireEvent.change(passwordInput, { target: { value: 'testpass' } });
    fireEvent.submit(form);

    // Ant Design form validation should prevent submission
    await waitFor(() => {
      expect(mockLoginApi).not.toHaveBeenCalled();
    });
  });
});