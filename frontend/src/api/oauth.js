import client from './client';

/**
 * OAuth 授权 API 封装
 * 配合后端 /api/oauth/* 端点，把"手动填 token"升级为"跳转平台授权"。
 * 流程：getAuthorizeUrl → 跳转平台 → 平台回调 /oauth/callback → exchangeCode 换 token
 */

/**
 * 获取某平台的 OAuth 授权页 URL
 * 后端会生成 state 并存库，回调时校验，防 CSRF。
 * @param {string} platform - 平台代码，如 douyin_star / chanmama
 * @returns {Promise<{authorize_url: string, state: string}>}
 */
export function getAuthorizeUrl(platform) {
  return client
    .get(`/oauth/authorize/${encodeURIComponent(platform)}`)
    .then((res) => res.data);
}

/**
 * 用平台回调返回的 code 换取访问令牌并绑定到当前公司
 * 若后端 callback 已在服务端自动处理（无需前端再调），则此函数可不被调用。
 * @param {string} platform - 平台代码
 * @param {string} code - 平台回调返回的授权码
 * @param {string} state - 与 getAuthorizeUrl 返回一致的 state，后端校验防 CSRF
 * @returns {Promise<{message?: string, platform?: string, bound?: boolean}>}
 */
export function exchangeCode(platform, code, state) {
  return client
    .post(`/oauth/callback/${encodeURIComponent(platform)}`, { code, state })
    .then((res) => res.data);
}
