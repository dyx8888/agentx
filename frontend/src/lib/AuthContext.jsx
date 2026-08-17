import { createContext, useContext, useState, useEffect, useCallback, useMemo } from 'react';
import client, { setAuthTokens, removeAuthTokens } from '@/api/client';
import { getMe } from '@/api/auth';

const AuthContext = createContext(null);

/* 从 JWT 解析用户名（不校验签名，仅用于本地显示） */
function parseUsernameFromToken(token) {
  try {
    const payload = JSON.parse(atob(token.split('.')[1]));
    return {
      id: payload.sub,
      username: payload.sub || '用户',
      email: payload.email || '',
    };
  } catch {
    return null;
  }
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [offline, setOffline] = useState(false);

  const logout = useCallback(async () => {
    // 调用后端撤销会话并清除 httpOnly cookie（client 已配置 withCredentials，cookie 自动带）。
    // 即使失败也忽略，继续清除前端状态。
    try {
      await client.post('/auth/token/logout');
    } catch {
      // 忽略后端调用失败，继续清除本地状态
    }
    // no-op：cookie 由后端清除；保留调用以兼容旧调用约定与单元测试
    removeAuthTokens();
    setUser(null);
  }, []);

  const login = useCallback(async (accessToken, refreshToken) => {
    // cookie 方案：登录响应的 Set-Cookie 已由浏览器自动存储，前端无需感知 token。
    // accessToken / refreshToken 参数仅为兼容旧调用方（LoginPage 仍传 token），这里忽略。
    // no-op：保留调用以兼容旧签名与单元测试
    setAuthTokens(accessToken, refreshToken);
    try {
      const data = await getMe();
      setUser(data);
    } catch {
      // 后端不可用 — 回退到 token payload（仅用于本地显示）
      const fallback = parseUsernameFromToken(accessToken);
      setUser(fallback || { username: '用户' });
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    // cookie 方案：不再从 localStorage 判断 token 存在。
    // 直接调 getMe（client 已配置 withCredentials，cookie 自动带）：
    //   200 = 已登录（cookie 有效）
    //   401 = 未登录 / cookie 失效
    (async () => {
      try {
        const data = await getMe();
        if (cancelled) return;
        setUser(data);
        setOffline(false);
      } catch (err) {
        if (cancelled) return;
        // 区分错误类型，避免后端未启动时误判为未登录（影响恢复后体验）
        const isNetworkError =
          !err?.response &&
          (err?.code === 'ERR_NETWORK' ||
           err?.message === 'Network Error' ||
           err?.name === 'TypeError');
        if (isNetworkError) {
          // 网络不可达（后端未启动 / 离线）— 标记离线，便于恢复后重试
          setUser(null);
          setOffline(true);
        } else {
          // 401（未登录 / cookie 失效）或其他错误 — 视为未登录
          // no-op：cookie 由后端清除；保留调用以兼容旧调用约定与单元测试
          removeAuthTokens();
          setUser(null);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const isAuthenticated = !!user;

  // setUser 是 useState setter，引用稳定，无需放入依赖；isAuthenticated 由 user 派生
  const value = useMemo(() => ({
    user, setUser, login, logout, loading, isAuthenticated, offline,
  }), [user, login, logout, loading, offline]);

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}
