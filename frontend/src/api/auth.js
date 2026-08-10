import client from './client';

/**
 * 用户登录
 * @param {string} username
 * @param {string} password
 * @returns {Promise<{access_token: string, refresh_token: string, token_type: string}>}
 */
export function login(username, password) {
  const params = new URLSearchParams();
  params.append('username', username);
  params.append('password', password);
  return client
    .post('/auth/token', params, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    })
    .then((res) => res.data);
}

/**
 * 用户注册
 * @param {Object} data - { username, password, email, company_name, brand_name, category }
 * @returns {Promise<Object>}
 */
export function register(data) {
  return client
    .post('/auth/users/register', data)
    .then((res) => res.data);
}

/**
 * 刷新 Token
 * @param {string} refreshToken
 * @returns {Promise<{access_token: string, refresh_token: string}>}
 */
export function refreshToken(refreshToken) {
  return client
    .post('/auth/token/refresh', { refresh_token: refreshToken })
    .then((res) => res.data);
}

/**
 * 获取当前用户信息
 * @returns {Promise<Object>}
 */
export function getMe() {
  return client.get('/auth/users/me').then((res) => res.data);
}

/**
 * 更新当前用户资料
 * @param {Object} profile - { username, company_name, brand_name, category, bio }
 * @returns {Promise<{success: boolean, message: string}>}
 */
export function updateUserProfile(profile) {
  return client
    .put('/auth/users/me', profile)
    .then((res) => res.data);
}