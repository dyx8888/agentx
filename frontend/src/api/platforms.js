import client from './client';

// ─── 平台元数据（T4.4 后端端点，无需 company_id） ──────────────────────────────

/**
 * 获取所有平台清单
 * @returns {Promise<Array<{code, name_display, icon, description, credential_fields, required}>>}
 */
export function getPlatforms() {
  return client.get('/platforms').then((res) => res.data);
}

/**
 * 获取某平台的凭证字段定义（前端据此动态渲染表单）
 * @param {string} code - 平台代码，如 douyin_star
 * @returns {Promise<{code: string, fields: Array<{field_name, label_zh, required, help_text}>}>}
 */
export function getCredentialFields(code) {
  return client
    .get(`/platforms/${code}/credential-fields`)
    .then((res) => res.data);
}

/**
 * 获取某平台的授权教程（图文引导步骤）
 * @param {string} code - 平台代码
 * @returns {Promise<{title: string, steps: Array<{step_num, action, note}>}>}
 */
export function getPlatformGuide(code) {
  return client.get(`/platforms/${code}/guide`).then((res) => res.data);
}

// ─── 公司平台凭证（T4.1 后端端点，需 company_id） ──────────────────────────────

/**
 * 获取公司已绑定平台的 masked 状态列表（不含敏感值）
 * @param {number|string} companyId
 * @returns {Promise<Array<{platform, bound, last_verified, last_verify_valid}>>}
 */
export function getBoundCredentials(companyId) {
  return client
    .get(`/admin/companies/${companyId}/credentials`)
    .then((res) => res.data);
}

/**
 * 绑定/更新公司某平台凭证（动态字段，前端只传不缓存）
 * @param {number|string} companyId
 * @param {string} platform - 平台代码
 * @param {Object<string,string>} credentials - 动态字段，如 { app_id, app_secret, ... }
 * @returns {Promise<{message: string}>}
 */
export function bindCredentials(companyId, platform, credentials) {
  return client
    .post(`/admin/companies/${companyId}/credentials`, { platform, credentials })
    .then((res) => res.data);
}

/**
 * 解绑公司某平台凭证
 * @param {number|string} companyId
 * @param {string} platform - 平台代码
 * @returns {Promise<{message: string}>}
 */
export function unbindCredentials(companyId, platform) {
  return client
    .delete(`/admin/companies/${companyId}/credentials`, { params: { platform } })
    .then((res) => res.data);
}

/**
 * 测试连接：验证公司某平台凭证有效性（后端调适配器 authenticate()）
 * @param {number|string} companyId
 * @param {string} platform - 平台代码
 * @returns {Promise<{valid: boolean, message: string}>}
 */
export function verifyCredentials(companyId, platform) {
  return client
    .post(`/admin/companies/${companyId}/credentials/${platform}/verify`)
    .then((res) => res.data);
}
