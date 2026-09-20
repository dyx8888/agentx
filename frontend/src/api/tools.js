import client from './client';

/**
 * 获取可用工具能力列表（供快捷指令动态生成）。
 * GET /api/tools/capabilities
 * @returns {Promise<Array<{key: string, label: string}>>}
 */
export function getToolCapabilities() {
  return client
    .get('/tools/capabilities')
    .then((res) => res.data);
}
