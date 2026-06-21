import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { getAuthToken, setAuthTokens, removeAuthTokens } from '@/api/client';
import { getMe } from '@/api/auth';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const logout = useCallback(() => {
    removeAuthTokens();
    setUser(null);
  }, []);

  const login = useCallback(async (accessToken, refreshToken) => {
    setAuthTokens(accessToken, refreshToken);
    try {
      const data = await getMe();
      setUser(data);
    } catch {
      // 如果获取用户信息失败，使用 token 中的 sub 作为用户名
      try {
        const payload = JSON.parse(atob(accessToken.split('.')[1]));
        setUser({ username: payload.sub });
      } catch {
        setUser({ username: 'demo' });
      }
    }
  }, []);

  useEffect(() => {
    const token = getAuthToken();
    if (!token) {
      setLoading(false);
      return;
    }
    getMe()
      .then((data) => setUser(data))
      .catch(() => removeAuthTokens())
      .finally(() => setLoading(false));
  }, []);

  const isAuthenticated = !!user;

  return (
    <AuthContext.Provider value={{ user, setUser, login, logout, loading, isAuthenticated }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}