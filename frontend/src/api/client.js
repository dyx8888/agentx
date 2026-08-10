import axios from 'axios';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api';
const REFRESH_LEEWAY = 120; // 提前 2 分钟刷新 Token（仅用于 isTokenExpired 工具函数）

// 401 跳转：仅在用户**曾经成功认证过**（任意请求成功过）时触发。
// 初次加载时的 401（如 getMe 后端未启动 / 未登录）由 AuthContext 自行处理 fallback。
let hasHadSuccessfulResponse = false;

// ========= Token 存储工具（httpOnly cookie 方案下为 no-op / 返回 null）=========
// 切换到 httpOnly cookie 后，前端不再持有 token：access_token / refresh_token 均由后端
// 通过 Set-Cookie 写入 httpOnly cookie，浏览器自动管理，JS 无法读取。
// 以下导出保留是为兼容仍依赖它们的旧代码（chat.js SSE、useWebSocket.js、
// FilePreviewModal.jsx、单元测试），这些调用方应逐步迁移到「同源请求自动带 cookie」。
export function getAuthToken() {
  // httpOnly cookie 对 JS 不可见，无法读取 token
  return null;
}

export function getRefreshToken() {
  return null;
}

export function setAuthTokens(_access, _refresh) {
  // no-op：token 由后端 Set-Cookie 写入 httpOnly cookie，前端无法也无需手动存储
}

export function removeAuthTokens() {
  // no-op：登出时由后端清 cookie（POST /auth/token/logout）
}

// ========= JWT 解析（保留供 AuthContext fallback 使用）=========
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
  // 关键：让所有请求自动携带 httpOnly cookie（access_token / refresh_token）。
  // 同源场景下浏览器默认会带 cookie，显式声明 withCredentials 以兼容跨域反代部署。
  withCredentials: true,
  headers: { 'Content-Type': 'application/json' },
});

// 请求拦截器：cookie 方案下不再手动注入 Authorization header。
// 浏览器同源请求会自动携带 cookie，后端从 cookie 读取 access_token 校验。
client.interceptors.request.use(
  (config) => config,
  (error) => Promise.reject(error)
);

// 响应拦截器：401 自动刷新重试 + 智能跳转 + 错误格式统一
client.interceptors.response.use(
  (response) => {
    hasHadSuccessfulResponse = true;
    return response;
  },
  async (error) => {
    const config = error.config;

    // 401 处理：先尝试刷新 cookie 后重试一次（refresh_token 在 cookie 里，withCredentials 自动带）。
    // 仅对未重试过的请求生效，避免无限循环。
    if (error.response?.status === 401 && config && !config._retried && hasHadSuccessfulResponse) {
      const isRefreshCall = config.url && config.url.includes('/auth/token/refresh');
      if (!isRefreshCall) {
        try {
          await _refreshToken();
          config._retried = true;
          return client(config);
        } catch {
          // 刷新失败 — 若应用已认证过则跳登录，否则交给 AuthContext fallback 处理
          if (hasHadSuccessfulResponse) {
            window.location.href = '/login';
          }
          return Promise.reject(error);
        }
      }
    }

    // 已认证会话期间的 401（refresh 失败 / refresh 接口本身 401）— 跳登录
    if (error.response?.status === 401 && hasHadSuccessfulResponse) {
      window.location.href = '/login';
    }

    // 重试逻辑：仅对 GET 请求的 5xx 和网络错误重试一次
    // 不重试 POST/PUT/DELETE（避免重复写入）、4xx（客户端错误，重试无意义）、401（已有 refresh/跳转逻辑）
    const isRetryable = config &&
                        !config._retry &&
                        config.method === 'get' &&
                        (error.code === 'ERR_NETWORK' ||
                         (error.response?.status >= 500 && error.response?.status < 600));

    if (isRetryable) {
      config._retry = true;
      return new Promise(resolve => setTimeout(resolve, 500))
        .then(() => client(config));
    }

    // 统一提取错误消息：兼容 FastAPI HTTPException（detail）和全局异常处理器（message）
    const errorData = error.response?.data;
    const message = errorData?.detail || errorData?.message || '请求失败';
    error.userMessage = message;

    return Promise.reject(error);
  }
);

// ========= Token 刷新（cookie 方案）=========
// 并发请求去重：多个请求同时 401 时复用同一个 refresh promise，避免重复调用后端
let refreshPromise = null;

async function _doRefresh() {
  // refresh_token 在 httpOnly cookie 里，withCredentials 让请求自动带 cookie。
  // 后端从 cookie 读取 refresh_token，校验后通过 Set-Cookie 写入新的 access_token cookie。
  // 用独立 axios 调用（不走 client 拦截器），避免 refresh 自身 401 时递归触发刷新。
  const res = await axios.post(
    `${API_BASE}/auth/token/refresh`,
    {},
    { withCredentials: true, timeout: 30000 }
  );
  // 后端 Set-Cookie 自动更新浏览器 cookie，前端无需感知 token 内容
  return res.data;
}

async function _refreshToken() {
  if (refreshPromise) return refreshPromise;
  refreshPromise = _doRefresh().finally(() => { refreshPromise = null; });
  return refreshPromise;
}

export default client;
