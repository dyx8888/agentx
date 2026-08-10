import client from './client';

/**
 * 审核通过
 * @param {string|number} toolResultId - 工具执行结果 ID
 * @returns {Promise<Object>}
 */
export function approveToolResult(toolResultId) {
  return client
    .post(`/admin/evolution/reviews/${toolResultId}/approve`)
    .then((res) => res.data);
}

/**
 * 审核驳回
 * @param {string|number} toolResultId - 工具执行结果 ID
 * @param {string} reason - 驳回理由
 * @returns {Promise<Object>}
 */
export function rejectToolResult(toolResultId, reason) {
  return client
    .post(`/admin/evolution/reviews/${toolResultId}/reject`)
    .then((res) => res.data);
}