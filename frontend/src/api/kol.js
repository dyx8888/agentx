import client from './client';

const API_BASE = '/kol';
const SOURCE_LABELS = {
  manual: '人工导入',
  manual_upload: '人工导入',
  public_web: '公开网页整理',
  cached_snapshot: '历史缓存快照',
  official_api: '平台授权数据',
  partner_api: '平台授权数据',
};

export function formatKolSourceLabel(source, sourceLabel) {
  if (sourceLabel) return sourceLabel;
  return SOURCE_LABELS[source] || source || '未知来源';
}

function normaliseSourceLabels(summary = {}, labels = {}) {
  return Object.fromEntries(
    Object.keys(summary || {}).map((source) => [source, formatKolSourceLabel(source, labels[source])])
  );
}

function normaliseKolRecord(record = {}) {
  const source = record.data_source || record.source || 'manual_upload';
  const followers = record.followers ?? record.follower_count ?? record.followers_count ?? 0;
  const sourceLabel = formatKolSourceLabel(source, record.source_label || record.sourceLabel);
  const sourceAvailable = record.source_available_for_search !== false
    && record.sourceAvailableForSearch !== false;

  return {
    ...record,
    source,
    data_source: source,
    source_label: sourceLabel,
    sourceLabel,
    followers,
    follower_count: followers,
    followers_count: followers,
    source_available_for_search: sourceAvailable,
    sourceAvailableForSearch: sourceAvailable,
  };
}

function normaliseKolResponse(data = {}) {
  const dataSourceSummary = data.data_source_summary || {};
  const sourceLabels = normaliseSourceLabels(dataSourceSummary, data.source_labels || {});

  return {
    ...data,
    data_source_summary: dataSourceSummary,
    source_labels: sourceLabels,
    results: Array.isArray(data.results) ? data.results.map(normaliseKolRecord) : [],
  };
}

export async function importKols(items, dryRun = false) {
  const res = await client.post(`${API_BASE}/import`, { items, dry_run: dryRun });
  const dataSourceSummary = res.data?.data_source_summary || {};
  return {
    ...res.data,
    data_source_summary: dataSourceSummary,
    source_labels: normaliseSourceLabels(dataSourceSummary, res.data?.source_labels || {}),
  };
}

export async function searchKols(payload) {
  const res = await client.post(`${API_BASE}/search`, payload);
  return normaliseKolResponse(res.data);
}
