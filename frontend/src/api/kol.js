import client from './client';

const API_BASE = '/kol';

export async function importKols(items, dryRun = false) {
  const res = await client.post(`${API_BASE}/import`, { items, dry_run: dryRun });
  return res.data;
}

export async function searchKols(payload) {
  const res = await client.post(`${API_BASE}/search`, payload);
  return res.data;
}
