import client from './client';

/**
 * 获取可用工具能力列表（供快捷指令动态生成）。
 * GET /api/admin/tools/capabilities
 * @returns {Promise<Array<{key: string, label: string}>>}
 */
export function getToolCapabilities() {
  return client
    .get('/admin/tools/capabilities')
    .then((res) => res.data);
}
