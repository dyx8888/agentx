import { render, screen, waitFor, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock the API modules using vi.hoisted
const { mockGetAuthToken, mockSetAuthTokens, mockRemoveAuthTokens, mockGetMe } = vi.hoisted(() => ({
  mockGetAuthToken: vi.fn(() => null),
  mockSetAuthTokens: vi.fn(),
  mockRemoveAuthTokens: vi.fn(),
  mockGetMe: vi.fn(),
}));

vi.mock('@/api/client', () => ({
  getAuthToken: mockGetAuthToken,
  setAuthTokens: mockSetAuthTokens,
  removeAuthTokens: mockRemoveAuthTokens,
}));

vi.mock('@/api/auth', () => ({
  getMe: mockGetMe,
}));

// Import after mocks
import { AuthProvider, useAuth } from '@/lib/AuthContext';

// Test component that uses the auth context
function TestConsumer({ onAuth }) {
  const auth = useAuth();
  // Expose auth values for assertion
  if (onAuth) onAuth(auth);
  return (
    <div>
      <span data-testid="loading">{auth.loading ? 'loading' : 'ready'}</span>
      <span data-testid="authenticated">{auth.isAuthenticated ? 'yes' : 'no'}</span>
      <span data-testid="user">{auth.user ? auth.user.username : 'none'}</span>
    </div>
  );
}

describe('AuthContext', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetAuthToken.mockReturnValue(null);
  });

  describe('AuthProvider', () => {
    it('renders children', async () => {
      render(
        <AuthProvider>
          <div data-testid="child">child content</div>
        </AuthProvider>
      );

      await waitFor(() => {
        expect(screen.getByTestId('child')).toBeInTheDocument();
      });
    });

    it('sets loading to false when no token exists', async () => {
      mockGetAuthToken.mockReturnValue(null);

      let authValue;
      render(
        <AuthProvider>
          <TestConsumer onAuth={(v) => { authValue = v; }} />
        </AuthProvider>
      );

      await waitFor(() => {
        expect(screen.getByTestId('loading')).toHaveTextContent('ready');
      });

      expect(authValue.loading).toBe(false);
      expect(authValue.isAuthenticated).toBe(false);
    });

    it('calls getMe when token exists', async () => {
      mockGetAuthToken.mockReturnValue('valid-token');
      mockGetMe.mockResolvedValue({ id: 1, username: 'testuser' });

      let authValue;
      render(
        <AuthProvider>
          <TestConsumer onAuth={(v) => { authValue = v; }} />
        </AuthProvider>
      );

      await waitFor(() => {
        expect(screen.getByTestId('user')).toHaveTextContent('testuser');
      });

      expect(mockGetMe).toHaveBeenCalled();
      expect(authValue.isAuthenticated).toBe(true);
    });

    it('handles getMe failure gracefully', async () => {
      mockGetAuthToken.mockReturnValue('invalid-token');
      mockGetMe.mockRejectedValue(new Error('Unauthorized'));

      let authValue;
      render(
        <AuthProvider>
          <TestConsumer onAuth={(v) => { authValue = v; }} />
        </AuthProvider>
      );

      await waitFor(() => {
        expect(screen.getByTestId('loading')).toHaveTextContent('ready');
      });

      expect(mockRemoveAuthTokens).toHaveBeenCalled();
      expect(authValue.isAuthenticated).toBe(false);
    });

    it('login calls setAuthTokens', async () => {
      mockGetAuthToken.mockReturnValue(null);

      let authValue;
      render(
        <AuthProvider>
          <TestConsumer onAuth={(v) => { authValue = v; }} />
        </AuthProvider>
      );

      await waitFor(() => {
        expect(screen.getByTestId('loading')).toHaveTextContent('ready');
      });

      act(() => {
        authValue.login('my-access-token', 'my-refresh-token');
      });

      expect(mockSetAuthTokens).toHaveBeenCalledWith('my-access-token', 'my-refresh-token');
    });

    it('logout calls removeAuthTokens and clears user', async () => {
      mockGetAuthToken.mockReturnValue('valid-token');
      mockGetMe.mockResolvedValue({ id: 1, username: 'testuser' });

      let authValue;
      render(
        <AuthProvider>
          <TestConsumer onAuth={(v) => { authValue = v; }} />
        </AuthProvider>
      );

      await waitFor(() => {
        expect(screen.getByTestId('user')).toHaveTextContent('testuser');
      });

      act(() => {
        authValue.logout();
      });

      expect(mockRemoveAuthTokens).toHaveBeenCalled();
      expect(authValue.user).toBeNull();
      expect(authValue.isAuthenticated).toBe(false);
    });
  });

  describe('useAuth', () => {
    it('throws error when used outside AuthProvider', () => {
      // Suppress console.error for this test
      const consoleError = console.error;
      console.error = vi.fn();

      function BadComponent() {
        useAuth();
        return null;
      }

      expect(() => render(<BadComponent />)).toThrow(
        'useAuth must be used inside AuthProvider'
      );

      console.error = consoleError;
    });
  });
});