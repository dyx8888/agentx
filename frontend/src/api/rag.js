import client from './client';

const API_BASE = '/rag'; // client.js 的 axios baseURL 已为 '/api'，这里不再重复前缀

/**
 * 获取嵌入模型列表
 * @returns {Promise<{models: Array, active_model: string}>}
 */
export async function listEmbeddingModels() {
  const res = await client.get(`${API_BASE}/embedding/models`);
  return res.data;
}

/**
 * 切换嵌入模型
 * @param {string} modelName - 模型名称
 * @returns {Promise<{status, previous_model, current_model}>}
 */
export async function switchEmbeddingModel(modelName) {
  const res = await client.put(`${API_BASE}/embedding/switch`, {
    model_name: modelName,
  });
  return res.data;
}

/**
 * 获取公司资料
 * @param {string} [companyId='1'] - 公司 ID
 * @returns {Promise<object>}
 */
export async function getCompanyProfile(companyId = '1') {
  const res = await client.get(`${API_BASE}/company/profile`, {
    params: { company_id: companyId },
  });
  return res.data;
}

/**
 * 更新公司资料
 * @param {object} profile - 公司资料对象
 * @param {string} [companyId='1'] - 公司 ID
 * @returns {Promise<object>}
 */
export async function updateCompanyProfile(profile, companyId = '1') {
  const res = await client.put(`${API_BASE}/company/profile`, profile, {
    params: { company_id: companyId },
  });
  return res.data;
}

/**
 * 获取 RAG 系统配置总览
 * @param {string} [companyId='1'] - 公司 ID
 * @returns {Promise<object>}
 */
export async function getRagConfig(companyId = '1') {
  const res = await client.get(`${API_BASE}/config`, {
    params: { company_id: companyId },
  });
  return res.data;
}

/**
 * 获取知识图谱实体列表
 * @returns {Promise<{entities: Array, entity_count: number, relation_count: number}>}
 */
export async function listGraphEntities() {
  const res = await client.get(`${API_BASE}/graph/entities`);
  return res.data;
}

/* ═══════════════════════════════════════════════════════════════
   嵌入服务配置 — 变更① T1.7（混合部署：本地 + API）
   ═══════════════════════════════════════════════════════════════ */

/**
 * 获取当前公司的嵌入服务配置
 * @returns {Promise<{mode: string, api_base_url?: string, model_name?: string, api_key_masked?: string}>}
 */
export async function getEmbeddingConfig() {
  const res = await client.get(`${API_BASE}/embedding/config`);
  return res.data;
}

/**
 * 更新嵌入服务配置（热切换，无需重启后端）
 * @param {object} config - {mode, api_base_url?, api_key?, model_name?}
 * @returns {Promise<object>}
 */
export async function updateEmbeddingConfig(config) {
  const res = await client.put(`${API_BASE}/embedding/config`, config);
  return res.data;
}

/**
 * 测试嵌入 API 连接（不存档，仅验证参数可用性）
 * @param {object} params - {mode, api_base_url, api_key, model_name}
 * @returns {Promise<{ok: boolean, dims?: number, latency_ms?: number, message?: string, error?: string}>}
 */
export async function testEmbeddingConnection(params) {
  const res = await client.post(`${API_BASE}/embedding/test`, params);
  return res.data;
}
