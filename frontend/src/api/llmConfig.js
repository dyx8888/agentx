import client from './client';

/**
 * 获取公司的 LLM 配置（脱敏）。
 * 后端从 Company.llm_api_key (EncryptedText) 读取多厂商配置 JSON，
 * apiKey 以 apiKeyMasked 形式返回（如 "sk-****abcd"），永不暴露明文。
 * @param {number|string} companyId - 公司 ID
 * @returns {Promise<{providers: Object}>}
 */
export function getLlmConfig(companyId) {
  return client
    .get(`/admin/companies/${companyId}/llm-config`)
    .then((res) => res.data);
}

/**
 * 更新公司的 LLM 配置。
 * apiKey 为空字符串表示保留原值（便于只改 gateway/限额不改 key）。
 * 后端使用 merge 语义：仅更新请求中包含的 provider，其他保留。
 * @param {number|string} companyId - 公司 ID
 * @param {Object} providers - { [providerKey]: { gateway, apiKey, tpm, usage, warnAt90 } }
 * @returns {Promise<{providers: Object}>}
 */
export function updateLlmConfig(companyId, providers) {
  return client
    .put(`/admin/companies/${companyId}/llm-config`, { providers })
    .then((res) => res.data);
}
