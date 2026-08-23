import client from './client';

const API_BASE = '/browser-connector';

export async function getBrowserConnectorStatus() {
  const res = await client.get(`${API_BASE}/status`);
  return res.data;
}

export async function listBrowserConnectorRecords(kind, limit = 50) {
  const params = { limit };
  if (kind) params.kind = kind;
  const res = await client.get(`${API_BASE}/records`, { params });
  return res.data;
}

export async function importBrowserConnectorKols(payload = {}) {
  const res = await client.post(`${API_BASE}/import/kols`, payload);
  return res.data;
}

export async function importBrowserConnectorKnowledge(payload = {}) {
  const res = await client.post(`${API_BASE}/import/knowledge`, payload);
  return res.data;
}

export async function listBrowserConnectorCampaignSnapshots(limit = 50) {
  const res = await client.get(`${API_BASE}/analytics/campaign-snapshots`, {
    params: { limit },
  });
  return res.data;
}
