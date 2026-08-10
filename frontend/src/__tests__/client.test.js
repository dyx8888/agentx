import { describe, it, expect } from 'vitest';
import client, {
  getAuthToken,
  getRefreshToken,
  setAuthTokens,
  removeAuthTokens,
  isTokenExpired,
} from '@/api/client';

// cookie 方案说明：
// 切换到 httpOnly cookie 后，access_token / refresh_token 均由后端通过 Set-Cookie 写入
// httpOnly cookie，浏览器自动管理，JS 无法读取 / 存储。因此下列 token 存取函数变为
// no-op / 返回 null，与 localStorage 时代的语义完全不同。

describe('client', () => {
  describe('cookie 方案：token 存取为 no-op / 返回 null', () => {
    it('getAuthToken 始终返回 null（token 在 httpOnly cookie 里，JS 读不到）', () => {
      expect(getAuthToken()).toBeNull();
    });

    it('getRefreshToken 始终返回 null', () => {
      expect(getRefreshToken()).toBeNull();
    });

    it('setAuthTokens 是 no-op，不会让 getAuthToken 返回非 null', () => {
      setAuthTokens('access-token', 'refresh-token');
      expect(getAuthToken()).toBeNull();
      expect(getRefreshToken()).toBeNull();
    });

    it('setAuthTokens 单参调用同样是 no-op', () => {
      setAuthTokens('access-only');
      expect(getAuthToken()).toBeNull();
      expect(getRefreshToken()).toBeNull();
    });

    it('removeAuthTokens 是 no-op（登出时由后端清 cookie）', () => {
      removeAuthTokens();
      expect(getAuthToken()).toBeNull();
      expect(getRefreshToken()).toBeNull();
    });
  });

  describe('axios 实例配置', () => {
    it('withCredentials=true，确保所有请求自动携带 httpOnly cookie', () => {
      expect(client.defaults.withCredentials).toBe(true);
    });

    it('baseURL 默认指向 /api', () => {
      expect(client.defaults.baseURL).toBe('/api');
    });
  });

  describe('isTokenExpired', () => {
    // isTokenExpired 仍保留：供 AuthContext fallback 判断 cookie 方案下
    // 后端返回的临时 token（若有）是否过期，逻辑与 localStorage 时代一致。
    it('returns true for null token', () => {
      expect(isTokenExpired(null)).toBe(true);
    });

    it('returns true for undefined token', () => {
      expect(isTokenExpired(undefined)).toBe(true);
    });

    it('returns true for empty string token', () => {
      expect(isTokenExpired('')).toBe(true);
    });

    it('returns true for expired token', () => {
      // Create a JWT that expired yesterday
      const header = btoa(JSON.stringify({ alg: 'HS256', typ: 'JWT' }));
      const payload = btoa(JSON.stringify({ exp: Math.floor(Date.now() / 1000) - 3600, sub: 'test' }));
      const signature = 'fake-signature';
      const expiredToken = `${header}.${payload}.${signature}`;
      expect(isTokenExpired(expiredToken)).toBe(true);
    });

    it('returns false for valid future token', () => {
      const header = btoa(JSON.stringify({ alg: 'HS256', typ: 'JWT' }));
      const payload = btoa(JSON.stringify({ exp: Math.floor(Date.now() / 1000) + 3600, sub: 'test' }));
      const signature = 'fake-signature';
      const validToken = `${header}.${payload}.${signature}`;
      expect(isTokenExpired(validToken)).toBe(false);
    });

    it('returns true for malformed token', () => {
      expect(isTokenExpired('not-a-valid-jwt')).toBe(true);
    });
  });
});
