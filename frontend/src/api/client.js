import axios from 'axios';

const API_BASE = '/api';
const REFRESH_LEEWAY = 120; // 提前 2 分钟刷新 Token

// ========= Token 存储工具 =========
function _stash(key, value) {
  try { localStorage.setItem(key, value); } catch { /* noop */ }
}

function _get(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}

function _del(key) {
  try { localStorage.removeItem(key); } catch { /* noop */ }
}

export function getAuthToken() {
  return _get('access_token');
}

export function getRefreshToken() {
  return _get('refresh_token');
}

export function setAuthTokens(access, refresh) {
  _stash('access_token', access);
  if (refresh) _stash('refresh_token', refresh);
}

export function removeAuthTokens() {
  _del('access_token');
  _del('refresh_token');
}

// ========= JWT 解析 =========
function _parseJwt(token) {
  try {
    const payload = token.split('.')[1];
    return JSON.parse(atob(payload));
  } catch {
    return null;
  }
}

export function isTokenExpired(token) {
  if (!token) return true;
  const decoded = _parseJwt(token);
  if (!decoded || !decoded.exp) return true;
  return Date.now() / 1000 > decoded.exp - REFRESH_LEEWAY;
}

// ========= Axios 实例 =========
const client = axios.create({
  baseURL: API_BASE,
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
});

// 请求拦截器：自动注入 Token
client.interceptors.request.use(
  async (config) => {
    let token = getAuthToken();

    if (token && isTokenExpired(token)) {
      try {
        token = await _refreshToken();
      } catch {
        removeAuthTokens();
        window.location.href = '/login';
        return Promise.reject(new Error('Session expired'));
      }
    }

    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// 响应拦截器：401 自动跳转登录
client.interceptors.response.use(
  (response) => response,
  async (error) => {
    if (error.response?.status === 401) {
      removeAuthTokens();
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

// ========= Token 刷新 =========
async function _refreshToken() {
  const refresh = getRefreshToken();
  if (!refresh) throw new Error('No refresh token');

  const res = await axios.post(`${API_BASE}/auth/token/refresh`, {
    refresh_token: refresh,
  });

  const { access_token, refresh_token } = res.data;
  setAuthTokens(access_token, refresh_token);
  return access_token;
}

export default client;