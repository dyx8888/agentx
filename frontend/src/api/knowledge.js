import client from './client';

const API_BASE = '/knowledge'; // client.js 的 axios baseURL 已为 '/api'，这里不再重复前缀

/**
 * 上传文档文件到知识库
 * @param {File} file - 文件对象
 * @param {string} companyId - 公司 ID
 * @param {string} [category] - 文档分类
 * @returns {Promise<{status, doc_id, filename, chunks, text_length}>}
 */
export async function uploadDocument(file, companyId, category = 'general') {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('company_id', companyId);
  formData.append('category', category);

  const res = await client.post(`${API_BASE}/upload-file`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return res.data;
}

/**
 * 获取知识库文档列表
 * @param {string} companyId - 公司 ID
 * @param {string} [category] - 分类过滤
 * @returns {Promise<{documents: Array, total: number}>}
 */
export async function listDocuments(companyId, category) {
  const params = { company_id: companyId };
  if (category) params.category = category;

  const res = await client.get(`${API_BASE}/documents`, { params });
  return res.data;
}

/**
 * 删除单个文档
 * @param {string} docId - 文档 ID
 * @param {string} companyId - 公司 ID
 * @returns {Promise<{status, message}>}
 */
export async function deleteDocument(docId, companyId) {
  const res = await client.delete(`${API_BASE}/documents/${docId}`, {
    params: { company_id: companyId },
  });
  return res.data;
}

/**
 * 清空所有文档
 * @param {string} companyId - 公司 ID
 * @returns {Promise<{status, message}>}
 */
export async function deleteAllDocuments(companyId) {
  const res = await client.delete(`${API_BASE}/documents`, {
    params: { company_id: companyId },
  });
  return res.data;
}

/**
 * 查询文档处理状态
 * @param {string} docId - 文档 ID
 * @returns {Promise<{doc_id, text_state, multimodal_state, is_fully_processed, has_failed, text_error, multimodal_error}>}
 */
export async function getDocumentStatus(docId) {
  const res = await client.get(`${API_BASE}/documents/${docId}/status`);
  return res.data;
}

/**
 * 搜索知识库
 * @param {string} query - 搜索关键词
 * @param {string} companyId - 公司 ID
 * @param {number} [nResults=5] - 返回结果数量
 * @returns {Promise<Array<{content, metadata, distance}>>}
 */
export async function searchKnowledge(query, companyId, nResults = 5) {
  const res = await client.get(`${API_BASE}/search`, {
    params: { query, company_id: companyId, n_results: nResults },
  });
  return res.data;
}

/**
 * 批量导入结构化知识
 * @param {Array<{content: string, category?: string, scenario?: string, title?: string, external_id?: string, data_source?: string, source_url?: string, source_note?: string, tags?: string[]}>} items
 * @param {boolean} [dryRun=false] - true 只校验不写入
 * @returns {Promise<{imported, skipped, dry_run, doc_ids, data_source_summary, data_source_warning, errors}>}
 */
export async function importKnowledge(items, dryRun = false) {
  const res = await client.post(`${API_BASE}/import`, {
    items,
    dry_run: dryRun,
  });
  return res.data;
}
