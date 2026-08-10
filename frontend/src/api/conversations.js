import client from './client';

/**
 * 获取对话列表
 * @param {Object} [params]
 * @param {number} [params.limit=20] - 每页数量
 * @param {number} [params.offset=0] - 偏移量
 * @returns {Promise<{total: number, items: Array}>}
 */
export function getConversations(params = {}) {
  return client
    .get('/conversations', { params })
    .then((res) => res.data);
}

/**
 * 创建新对话
 * @param {Object} [data]
 * @param {string} [data.title] - 对话标题
 * @returns {Promise<Object>}
 */
export function createConversation(data = {}) {
  return client
    .post('/conversations', data)
    .then((res) => res.data);
}

/**
 * 获取对话详情（含消息列表）
 * @param {number|string} id - 对话 ID
 * @returns {Promise<Object>}
 */
export function getConversation(id) {
  return client
    .get(`/conversations/${id}`)
    .then((res) => res.data);
}

/**
 * 删除对话
 * @param {number|string} id - 对话 ID
 * @returns {Promise<void>}
 */
export function deleteConversation(id) {
  return client.delete(`/conversations/${id}`);
}

/**
 * 获取对话关联的文件列表
 * 后端从消息的 references_json / metadata_json 中还原文件，
 * 按 source 分为「我上传的」(uploaded) 与「Agent 生成」(agent)。
 * @param {number|string} id - 对话 ID
 * @returns {Promise<{items: Array}>}
 */
export function getConversationFiles(id) {
  return client
    .get(`/conversations/${id}/files`)
    .then((res) => res.data);
}