import client from './client';

const API_BASE = '/browser-connector';

export async function createCaptureJob(payload) {
  const res = await client.post(`${API_BASE}/capture-jobs`, payload);
  return res.data;
}

export async function listCaptureJobs(conversationId, limit = 30) {
  const params = { limit };
  if (conversationId) params.conversation_id = conversationId;
  const res = await client.get(`${API_BASE}/capture-jobs`, { params });
  return res.data;
}

export async function getCaptureJob(jobId) {
  const res = await client.get(`${API_BASE}/capture-jobs/${jobId}`);
  return res.data;
}

export async function refreshCaptureJobTicket(jobId) {
  const res = await client.post(`${API_BASE}/capture-jobs/${jobId}/ticket`);
  return res.data;
}

export async function classifyCaptureJob(jobId) {
  const res = await client.post(`${API_BASE}/capture-jobs/${jobId}/classify`);
  return res.data;
}

export async function createCaptureDraft(jobId, draftKind) {
  const res = await client.post(`${API_BASE}/capture-jobs/${jobId}/draft`, {
    draft_kind: draftKind,
  });
  return res.data;
}

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
