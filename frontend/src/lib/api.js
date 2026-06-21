const API_BASE = '/api';

const REFRESH_LEEWAY = 120;

function _stash(key, value) {
  try { localStorage.setItem(key, value); } catch { /* noop */ }
}

function _get(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}

function _del(key) {
  try { localStorage.removeItem(key); } catch { /* noop */ }
}

export function getAuthToken() {
  return _get('access_token');
}

export function getRefreshToken() {
  return _get('refresh_token');
}

export function setAuthTokens(access, refresh) {
  _stash('access_token', access);
  _stash('refresh_token', refresh);
}

export function removeAuthTokens() {
  _del('access_token');
  _del('refresh_token');
}

function _parseJwt(token) {
  try {
    const payload = token.split('.')[1];
    return JSON.parse(atob(payload));
  } catch {
    return null;
  }
}

export function isTokenExpired(token) {
  if (!token) return true;
  const decoded = _parseJwt(token);
  if (!decoded || !decoded.exp) return true;
  return Date.now() / 1000 > decoded.exp - REFRESH_LEEWAY;
}

async function _refreshToken() {
  const refresh = getRefreshToken();
  if (!refresh) throw new Error('No refresh token');
  const res = await fetch(`${API_BASE}/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refresh }),
  });
  if (!res.ok) {
    removeAuthTokens();
    throw new Error('Refresh failed');
  }
  const data = await res.json();
  setAuthTokens(data.access_token, data.refresh_token);
  return data.access_token;
}

export async function fetchWithAuth(endpoint, options = {}) {
  let token = getAuthToken();

  if (token && isTokenExpired(token)) {
    try {
      token = await _refreshToken();
    } catch {
      removeAuthTokens();
      window.location.href = '/login';
      throw new Error('Session expired');
    }
  }

  const headers = {
    'Content-Type': 'application/json',
    ...options.headers,
  };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const res = await fetch(`${API_BASE}${endpoint}`, { ...options, headers });

  if (res.status === 401) {
    removeAuthTokens();
    window.location.href = '/login';
    throw new Error('Unauthorized');
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const err = new Error(body.detail || `HTTP ${res.status}`);
    err.status = res.status;
    err.data = body;
    throw err;
  }

  return res.json();
}

/* ========= Auth API ========= */
export function loginApi(username, password) {
  const params = new URLSearchParams();
  params.append('username', username);
  params.append('password', password);
  return fetch(`${API_BASE}/auth/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: params,
  }).then(async (r) => {
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: '登录失败' }));
      throw new Error(err.detail || `登录失败 (${r.status})`);
    }
    return r.json();
  });
}

export function getMe() {
  return fetchWithAuth('/auth/users/me');
}

/* ========= Dashboard API ========= */
export function getDashboardOverview(companyId) {
  return fetchWithAuth(`/dashboard/overview?company_id=${companyId}`);
}

export function getDashboardAgents(companyId) {
  return fetchWithAuth(`/dashboard/agents?company_id=${companyId}`);
}

export function getDashboardReviews(companyId, level) {
  let url = `/dashboard/reviews?company_id=${companyId}`;
  if (level) url += `&level=${level}`;
  return fetchWithAuth(url);
}

export function approveReview(reviewId, comment) {
  return fetchWithAuth(`/dashboard/reviews/${reviewId}/approve`, {
    method: 'POST',
    body: JSON.stringify({ comment }),
  });
}

export function rejectReview(reviewId, reason) {
  return fetchWithAuth(`/dashboard/reviews/${reviewId}/reject`, {
    method: 'POST',
    body: JSON.stringify({ reason }),
  });
}

export function getDashboardAlerts(companyId) {
  return fetchWithAuth(`/dashboard/alerts?company_id=${companyId}`);
}

export function markAlertRead(alertId) {
  return fetchWithAuth(`/dashboard/alerts/${alertId}/read`, { method: 'POST' });
}

export function getDashboardTaskTrend(companyId, days) {
  return fetchWithAuth(`/dashboard/task-trend?company_id=${companyId}&days=${days || 30}`);
}

export function getDashboardTokenConsumption(companyId, days) {
  return fetchWithAuth(`/dashboard/token-consumption?company_id=${companyId}&days=${days || 30}`);
}

/* ========= Agent API ========= */
export function getAgents(companyId) {
  return fetchWithAuth(`/agents?company_id=${companyId}`);
}

export function getAgent(agentId) {
  return fetchWithAuth(`/agents/${agentId}`);
}

export function updateAgentConfig(agentId, data) {
  return fetchWithAuth(`/agents/${agentId}/config`, {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}

export function chatWithAgent(agentId, message, callback) {
  return new Promise((resolve, reject) => {
    const token = getAuthToken();
    fetch(`${API_BASE}/chat/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ message, agent_id: agentId }),
    }).then(async (res) => {
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Chat failed');
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6);
            if (data === '[DONE]') { callback({ done: true }); resolve(); return; }
            try {
              callback(JSON.parse(data));
            } catch { /* skip malformed */ }
          }
        }
      }
      resolve();
    }).catch(reject);
  });
}

/* ========= Task API ========= */
export function getTasks(companyId, params) {
  const qs = new URLSearchParams({ company_id: companyId, ...params }).toString();
  return fetchWithAuth(`/tasks?${qs}`);
}

export function getTask(taskId) {
  return fetchWithAuth(`/tasks/${taskId}`);
}

export function createTask(data) {
  return fetchWithAuth('/tasks', { method: 'POST', body: JSON.stringify(data) });
}

export function cancelTask(taskId) {
  return fetchWithAuth(`/tasks/${taskId}/cancel`, { method: 'POST' });
}

/* ========= Admin API ========= */
export function getAdminCompanies() {
  return fetchWithAuth('/admin/companies');
}

export function getAdminUsage(days) {
  return fetchWithAuth(`/admin/usage?days=${days || 30}`);
}

export function getAdminSubscriptions() {
  return fetchWithAuth('/admin/subscriptions');
}

/* ========= Settings API ========= */
export function getCompanySettings(companyId) {
  return fetchWithAuth(`/company/${companyId}/settings`);
}

export function updateCompanySettings(companyId, data) {
  return fetchWithAuth(`/company/${companyId}/settings`, {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}

export function getCustomAgents(companyId) {
  return fetchWithAuth(`/company/${companyId}/custom-agents`);
}

export function createCustomAgent(companyId, data) {
  return fetchWithAuth(`/company/${companyId}/custom-agents`, {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export function deleteCustomAgent(companyId, agentId) {
  return fetchWithAuth(`/company/${companyId}/custom-agents/${agentId}`, {
    method: 'DELETE',
  });
}
