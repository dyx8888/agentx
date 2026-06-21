import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock localStorage before importing
const store = {};
const localStorageMock = {
  getItem: vi.fn((key) => store[key] || null),
  setItem: vi.fn((key, value) => { store[key] = value; }),
  removeItem: vi.fn((key) => { delete store[key]; }),
  clear: vi.fn(() => { Object.keys(store).forEach(k => delete store[k]); }),
};
Object.defineProperty(window, 'localStorage', { value: localStorageMock });

import {
  getAuthToken,
  getRefreshToken,
  setAuthTokens,
  removeAuthTokens,
  isTokenExpired,
} from '@/api/client';

describe('client', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    Object.keys(store).forEach(k => delete store[k]);
  });

  describe('getAuthToken', () => {
    it('returns null when no token is stored', () => {
      expect(getAuthToken()).toBeNull();
    });

    it('returns stored access token', () => {
      store['access_token'] = 'test-token';
      expect(getAuthToken()).toBe('test-token');
    });
  });

  describe('getRefreshToken', () => {
    it('returns null when no refresh token is stored', () => {
      expect(getRefreshToken()).toBeNull();
    });

    it('returns stored refresh token', () => {
      store['refresh_token'] = 'test-refresh';
      expect(getRefreshToken()).toBe('test-refresh');
    });
  });

  describe('setAuthTokens', () => {
    it('stores access and refresh tokens', () => {
      setAuthTokens('access-token', 'refresh-token');
      expect(store['access_token']).toBe('access-token');
      expect(store['refresh_token']).toBe('refresh-token');
    });

    it('stores only access token when refresh is not provided', () => {
      setAuthTokens('access-only');
      expect(store['access_token']).toBe('access-only');
      expect(store['refresh_token']).toBeUndefined();
    });
  });

  describe('removeAuthTokens', () => {
    it('removes both tokens', () => {
      store['access_token'] = 'access';
      store['refresh_token'] = 'refresh';
      removeAuthTokens();
      expect(store['access_token']).toBeUndefined();
      expect(store['refresh_token']).toBeUndefined();
    });
  });

  describe('isTokenExpired', () => {
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