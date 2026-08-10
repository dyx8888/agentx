import client from './client';

// ─── 成本管理（admin） ───────────────────────────────────────────────
// 后端：app.api.admin.costs（统一挂载前缀 /api/admin/costs）
// 业务含义：管理员查看 LLM 调用花费 / Token 用量

/**
 * 获取今日成本汇总
 * GET /api/admin/costs/today
 * @returns {Promise<{date: string, total_cost: number, total_requests: number, total_input_tokens: number, total_output_tokens: number}>}
 */
export function getTodayCost() {
  return client.get('/admin/costs/today').then((res) => res.data);
}

/**
 * 获取成本汇总（含按模型明细）
 * GET /api/admin/costs/summary?days=30
 * @param {number} [days=30] - 统计周期（天）
 * @returns {Promise<{
 *   total_cost: number,
 *   total_requests: number,
 *   total_input_tokens: number,
 *   total_output_tokens: number,
 *   period_days: number,
 *   cost_by_model: Array<{model_name, total_cost, total_requests, total_input_tokens, total_output_tokens}>,
 *   cost_by_agent: Array
 * }>}
 */
export function getCostSummary(days = 30) {
  return client
    .get('/admin/costs/summary', { params: { days } })
    .then((res) => res.data);
}
