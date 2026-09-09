importScripts("platform-policy.js");

const DEFAULT_SETTINGS = {
  enabled: true,
  endpoint: ""
};

const MAX_LOG_ENTRIES = 50;
const INGEST_PATH = "/api/browser-connector/ingest";
const LOCAL_DEV_HOSTS = new Set(["localhost", "127.0.0.1"]);
const AGENTX_VERCEL_HOST_PATTERN = /^agentx(?:-[a-z0-9-]+)?-dyx8888s-projects\.vercel\.app$/i;
const CAPTURE_JOBS_SESSION_KEY = "captureJobs";
const ACTIVE_CAPTURE_JOB_SESSION_KEY = "activeCaptureJobId";
const MAX_CAPTURE_DEPTH = 6;
const MAX_CAPTURE_ARRAY_ITEMS = 50;
const MAX_CAPTURE_OBJECT_KEYS = 100;
const GENERIC_CAPTURE_WINDOW_MS = 60_000;
const SENSITIVE_KEY_PATTERN = /(^|_|-)(authorization|auth|cookie|token|access_token|refresh_token|password|passwd|pwd|secret|captcha|verification|verify_code|sms_code|otp|payment|pay_password|card|cvv|credential|session|id_card|identity|email|e_mail|mail|phone|mobile|telephone|wechat|weixin|wx_id|qq|address)(_|-|$)/i;
const TOKEN_LIKE_PATTERN = /\b(?:[A-Za-z0-9_-]+\.){2}[A-Za-z0-9_-]+\b|\b[A-Za-z0-9._~-]{64,}\b/g;
const CARD_LIKE_PATTERN = /\b(?:\d[ -]*?){13,19}\b/g;
const EMAIL_LIKE_PATTERN = /\b[^\s@]+@[^\s@]+\.[^\s@]+\b/g;
const PHONE_LIKE_PATTERN = /\b(?:\+?86[-\s]?)?1[3-9]\d{9}\b/g;
const genericCaptureExpiries = new Map();
const captureJobs = new Map();
let activeCaptureJobId = null;
let captureJobsLoaded = false;
let captureJobsLoadPromise = null;

chrome.runtime.onInstalled.addListener(async () => {
  const existing = await chrome.storage.local.get(["settings"]);
  if (!existing.settings) {
    await chrome.storage.local.set({ settings: DEFAULT_SETTINGS, deliveries: [] });
    return;
  }

  const { settings, endpointCheck, changed } = normalizeSettings(existing.settings);
  if (endpointCheck.ok && changed) {
    await chrome.storage.local.set({ settings });
  }
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message) {
    return false;
  }

  if (message.type === "AGENTX_CONNECTOR_ENABLE_GENERIC_CAPTURE") {
    enableGenericCapture(message.tabId)
      .then((result) => sendResponse(result))
      .catch((error) => sendResponse({ ok: false, error: String(error && error.message ? error.message : error) }));
    return true;
  }

  if (message.type === "AGENTX_CONNECTOR_CAPTURE_CURRENT_PAGE") {
    captureCurrentPage(message.tabId)
      .then((result) => sendResponse({ ok: true, result }))
      .catch((error) => sendResponse({ ok: false, error: String(error && error.message ? error.message : error) }));
    return true;
  }

  if (message.type === "AGENTX_CONNECTOR_AGENTX_PAGE_READY") {
    synchronizeEndpointFromAgentXTab(sender)
      .then((endpoint) => sendResponse({ ok: Boolean(endpoint), endpoint }))
      .catch((error) => sendResponse({ ok: false, error: String(error && error.message ? error.message : error) }));
    return true;
  }

  if (message.type === "AGENTX_CONNECTOR_SYNC_ENDPOINT") {
    synchronizeEndpointFromAgentXTab(sender)
      .then((endpoint) => sendResponse({ ok: Boolean(endpoint), endpoint }))
      .catch((error) => sendResponse({ ok: false, error: String(error && error.message ? error.message : error) }));
    return true;
  }

  if (message.type === "AGENTX_CONNECTOR_SET_CAPTURE_JOB") {
    Promise.all([
      synchronizeEndpointFromAgentXTab(sender),
      rememberCaptureJob(message.captureJob)
    ])
      .then(([, job]) => sendResponse({ ok: Boolean(job), captureJob: job ? captureJobSummary(job) : null }))
      .catch((error) => sendResponse({ ok: false, error: String(error && error.message ? error.message : error) }));
    return true;
  }

  if (message.type === "AGENTX_CONNECTOR_GET_CAPTURE_JOBS") {
    getCaptureJobsForPopup()
      .then((result) => sendResponse(result))
      .catch((error) => sendResponse({ ok: false, error: String(error && error.message ? error.message : error) }));
    return true;
  }

  if (message.type === "AGENTX_CONNECTOR_SELECT_CAPTURE_JOB") {
    const id = Number(message.captureJobId);
    selectCaptureJob(id)
      .then(() => sendResponse({ ok: activeCaptureJobId !== null, activeCaptureJobId }))
      .catch((error) => sendResponse({ ok: false, error: String(error && error.message ? error.message : error) }));
    return true;
  }

  if (message.type !== "AGENTX_CONNECTOR_CAPTURE") {
    return false;
  }

  handleCapture(message.payload, sender)
    .then((result) => sendResponse({ ok: true, result }))
    .catch((error) => sendResponse({ ok: false, error: String(error && error.message ? error.message : error) }));

  return true;
});

async function enableGenericCapture(tabId) {
  if (!Number.isInteger(tabId)) {
    return { ok: false, reason: "invalid_tab" };
  }
  const tab = await chrome.tabs.get(tabId);
  const policy = globalThis.AgentXConnectorPlatformPolicy;
  if (!tab || !tab.url || !policy || !policy.isPageCaptureAllowed(tab.url) || isAgentXAppPage(tab.url)) {
    return { ok: false, reason: "blocked_page" };
  }
  await chrome.scripting.executeScript({
    target: { tabId },
    files: ["src/platform-policy.js", "src/content-script.js"]
  });
  await chrome.scripting.executeScript({
    target: { tabId },
    world: "MAIN",
    files: ["src/injected.js"]
  });
  await chrome.scripting.executeScript({
    target: { tabId },
    world: "MAIN",
    func: (expiresAt) => {
      window.__AGENTX_CONNECTOR_GENERIC_CAPTURE_UNTIL__ = expiresAt;
      window.dispatchEvent(new CustomEvent("agentx-browser-connector-enable-generic-api"));
    },
    args: [Date.now() + GENERIC_CAPTURE_WINDOW_MS]
  });
  genericCaptureExpiries.set(tabId, Date.now() + GENERIC_CAPTURE_WINDOW_MS);
  return { ok: true };
}

async function captureCurrentPage(tabId) {
  if (!Number.isInteger(tabId) || !hasActiveGenericCapture(tabId)) {
    return { captured: false, reason: "capture_not_enabled" };
  }

  const tab = await chrome.tabs.get(tabId);
  if (!tab || !tab.url || isAgentXAppPage(tab.url)) {
    return { captured: false, reason: "blocked_page" };
  }
  const [{ result }] = await chrome.scripting.executeScript({
    target: { tabId },
    func: () => {
      const MAX_VISIBLE_TEXT_LENGTH = 8000;
      const MAX_HEADING_COUNT = 20;
      const MAX_META_ITEMS = 12;
      const MAX_JSON_LD_ITEMS = 10;
      const MAX_OBJECT_KEYS = 80;
      const MAX_ARRAY_ITEMS = 30;
      const MAX_DEPTH = 5;
      const sensitiveKeyPattern = /(^|_|-)(authorization|auth|cookie|token|access_token|refresh_token|password|passwd|pwd|secret|captcha|verification|verify_code|sms_code|otp|payment|pay_password|card|cvv|credential|session|id_card|identity|email|e_mail|mail|phone|mobile|telephone|wechat|weixin|wx_id|qq|address)(_|-|$)/i;
      const emailPattern = /\b[^\s@]+@[^\s@]+\.[^\s@]+\b/g;
      const phonePattern = /\b(?:\+?86[-\s]?)?1[3-9]\d{9}\b/g;
      const cardPattern = /\b(?:\d[ -]*?){13,19}\b/g;
      const tokenPattern = /\b(?:[A-Za-z0-9_-]+\.){2}[A-Za-z0-9_-]+\b|\b[A-Za-z0-9._~-]{64,}\b/g;
      const safeMetaNames = new Set(["description", "keywords", "application-name", "og:title", "og:description", "og:type", "twitter:title", "twitter:description", "article:section"]);
      const safeUrl = (rawUrl) => {
        try {
          const parsed = new URL(String(rawUrl || ""), window.location.href);
          return `${parsed.origin}${parsed.pathname}`;
        } catch (_error) {
          return null;
        }
      };
      const sanitizeText = (value) => String(value || "")
        .replace(emailPattern, "[REDACTED_EMAIL]")
        .replace(phonePattern, "[REDACTED_PHONE]")
        .replace(cardPattern, "[REDACTED_CARD]")
        .replace(tokenPattern, "[REDACTED_TOKEN]");
      const sanitizeValue = (value, depth = 0) => {
        if (depth > MAX_DEPTH) return "[MaxDepth]";
        if (value == null || typeof value === "number" || typeof value === "boolean") return value;
        if (typeof value === "string") return sanitizeText(value);
        if (Array.isArray(value)) return value.slice(0, MAX_ARRAY_ITEMS).map((item) => sanitizeValue(item, depth + 1));
        if (typeof value === "object") {
          const object = {};
          Object.keys(value).slice(0, MAX_OBJECT_KEYS).forEach((key) => {
            if (!sensitiveKeyPattern.test(key)) object[key] = sanitizeValue(value[key], depth + 1);
          });
          return object;
        }
        return null;
      };
      const pageUrl = safeUrl(window.location.href);
      if (!pageUrl) return null;
      const meta = {};
      Array.from(document.querySelectorAll("meta[name], meta[property]")).some((node) => {
        const name = String(node.getAttribute("name") || node.getAttribute("property") || "").trim().toLowerCase();
        if (safeMetaNames.has(name)) {
          const content = sanitizeText(node.getAttribute("content") || "").trim();
          if (content) meta[name] = content;
        }
        return Object.keys(meta).length >= MAX_META_ITEMS;
      });
      const structuredData = [];
      Array.from(document.querySelectorAll('script[type="application/ld+json"]')).slice(0, MAX_JSON_LD_ITEMS).forEach((node) => {
        try { structuredData.push(sanitizeValue(JSON.parse(node.textContent || "null"))); } catch (_error) { /* Ignore invalid JSON-LD. */ }
      });
      return {
        captured_at: new Date().toISOString(),
        page: { url: pageUrl, title: sanitizeText(document.title || ""), referrer: safeUrl(document.referrer) },
        api: { url: pageUrl, method: "GET", status_code: null, matched_rule: "generic-web-page", response_mime: "text/html", captured_from: "fetch" },
        data: {
          kind: "generic_web_page",
          title: sanitizeText(document.title || ""),
          headings: Array.from(document.querySelectorAll("h1, h2, h3")).map((node) => sanitizeText(node.innerText || node.textContent || "").trim()).filter(Boolean).slice(0, MAX_HEADING_COUNT),
          visible_text: sanitizeText(String((document.body || document.documentElement).innerText || "")).slice(0, MAX_VISIBLE_TEXT_LENGTH),
          meta,
          structured_data: structuredData
        }
      };
    }
  });
  if (!result) {
    return { captured: false, reason: "content_capture_unavailable" };
  }

  const delivery = await handleCapture(result, { tab });
  return { captured: true, delivery };
}

function isAgentXAppPage(rawUrl) {
  try {
    const hostname = new URL(rawUrl).hostname;
    return hostname === "localhost" || hostname === "127.0.0.1" ||
      hostname === "agentx-fnbfc0d1r-dyx8888s-projects.vercel.app" ||
      /^agentx-[a-z0-9-]+\.vercel\.app$/i.test(hostname);
  } catch (_error) {
    return true;
  }
}

async function handleCapture(capture, sender) {
  const stored = await chrome.storage.local.get(["settings"]);
  const { settings: effectiveSettings, endpointCheck, changed } = normalizeSettings(
    stored.settings || DEFAULT_SETTINGS
  );
  if (endpointCheck.ok && changed) {
    await chrome.storage.local.set({ settings: effectiveSettings });
  }

  if (!effectiveSettings.enabled) {
    return recordDelivery({
      ok: false,
      skipped: true,
      reason: "disabled",
      capturedAt: capture && capture.captured_at
    });
  }

  const deliveredAt = new Date().toISOString();
  if (!endpointCheck.ok) {
    return recordDelivery({
      ok: false,
      skipped: true,
      reason: "invalid_endpoint",
      deliveredAt,
      error: endpointCheck.error
    });
  }

  const endpoint = endpointCheck.endpoint;
  if (!isAllowedCapture(capture, sender)) {
    return recordDelivery({
      ok: false,
      skipped: true,
      reason: "capture_not_allowlisted",
      deliveredAt
    });
  }
  const captureJob = await getActiveCaptureJob();
  if (captureJob && !captureMatchesJob(capture, sender, captureJob)) {
    return recordDelivery({
      ok: false,
      skipped: true,
      reason: "capture_outside_task_target",
      deliveredAt
    });
  }
  const payload = buildIngestPayload(capture, sender, captureJob);

  if (!isReadOnlyCaptureMethod(payload.api && payload.api.method)) {
    return recordDelivery({
      ok: false,
      skipped: true,
      reason: "non_readonly_method",
      deliveredAt,
      apiUrl: payload.api && payload.api.url,
      matchedRule: payload.api && payload.api.matched_rule
    });
  }

  try {
    const response = await fetch(endpoint, {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        "X-AgentX-Connector-Version": "0.1.0"
      },
      body: JSON.stringify(payload)
    });

    const delivery = await recordDelivery({
      ok: response.ok,
      status: response.status,
      endpoint,
      deliveredAt,
      apiUrl: payload.api && payload.api.url,
      matchedRule: payload.api && payload.api.matched_rule
    });
    if (response.ok && captureJob) {
      captureJobs.delete(captureJob.id);
      if (activeCaptureJobId === captureJob.id) activeCaptureJobId = null;
      await persistCaptureJobs();
    }
    return delivery;
  } catch (error) {
    return recordDelivery({
      ok: false,
      endpoint,
      deliveredAt,
      error: String(error && error.message ? error.message : error),
      apiUrl: payload.api && payload.api.url,
      matchedRule: payload.api && payload.api.matched_rule
    });
  }
}

function buildIngestPayload(capture, sender, captureJob = null) {
  const tabUrl = sender && sender.tab && sender.tab.url ? safeUrl(sender.tab.url) : null;
  const api = buildApiCaptureMetadata(capture && capture.api);
  const page = buildPageMetadata(capture && capture.page, tabUrl);

  const payload = {
    connector: {
      source: "chrome-extension-mv3",
      extension_id: chrome.runtime && chrome.runtime.id ? chrome.runtime.id : null,
      version: "0.2.0",
      mode: "readonly"
    },
    captured_at: capture && capture.captured_at ? capture.captured_at : new Date().toISOString(),
    page,
    api,
    data: normalizeStructuredData(capture && capture.data),
    policy: {
      whitelist_rule: api.matched_rule,
      redaction_version: "v2",
      contains_credentials: false,
      contains_sensitive_fields: false,
      platform_write_operation: false
    }
  };
  if (captureJob) {
    payload.capture_job_id = captureJob.id;
    payload.capability_ticket = captureJob.capability_ticket;
  }
  return payload;
}

function buildPageMetadata(capturePage, tabUrl) {
  const payload = {
    url: tabUrl || "about:blank",
    title: capturePage && capturePage.title ? sanitizeCaptureText(capturePage.title).slice(0, 300) : null,
    referrer: capturePage && capturePage.referrer ? safeUrl(capturePage.referrer) : null
  };
  return payload;
}

function buildApiCaptureMetadata(api) {
  const statusCode = Number(api && (api.status_code || api.status)) || 0;
  return {
    url: api && api.url ? safeUrl(api.url) || "about:blank" : "about:blank",
    method: String((api && api.method) || "GET").toUpperCase(),
    status_code: statusCode >= 100 && statusCode <= 599 ? statusCode : null,
    matched_rule: String((api && (api.matched_rule || api.matchedRule)) || "allowlisted-api").slice(0, 120),
    response_mime: api && (api.response_mime || api.response_content_type)
      ? String(api.response_mime || api.response_content_type).slice(0, 120)
      : null,
    captured_from: normalizeCapturedFrom(api && api.captured_from)
  };
}

function normalizeCapturedFrom(value) {
  const normalized = String(value || "").toLowerCase();
  if (normalized === "xmlhttprequest") {
    return "xmlhttprequest";
  }
  return "fetch";
}

async function recordDelivery(entry) {
  const existing = await chrome.storage.local.get(["deliveries"]);
  const deliveries = Array.isArray(existing.deliveries) ? existing.deliveries : [];
  const next = [entry, ...deliveries].slice(0, MAX_LOG_ENTRIES);
  await chrome.storage.local.set({ deliveries: next, lastDelivery: entry });
  return entry;
}

function validateEndpoint(endpoint) {
  let parsed;
  try {
    parsed = normalizeEndpointInput(endpoint);
  } catch (_error) {
    return { ok: false, error: "endpoint must be a valid URL" };
  }

  if (parsed.username || parsed.password) {
    return { ok: false, error: "endpoint must not contain URL credentials" };
  }
  if (parsed.search || parsed.hash) {
    return { ok: false, error: "endpoint must not contain query strings or fragments" };
  }
  if (parsed.pathname !== INGEST_PATH) {
    return { ok: false, error: `endpoint path must be ${INGEST_PATH}` };
  }

  const isLocalHttp =
    parsed.protocol === "http:" && LOCAL_DEV_HOSTS.has(parsed.hostname);
  const isHttps = parsed.protocol === "https:";
  if (!isLocalHttp && !isHttps) {
    return { ok: false, error: "endpoint must use https, except local development hosts" };
  }
  if (!endpointMatchesHostPermission(parsed) && !isTrustedAgentXEndpoint(parsed)) {
    return { ok: false, error: "endpoint origin is not granted by the extension manifest" };
  }

  return { ok: true, endpoint: parsed.href };
}

function isAllowedCapture(capture, sender) {
  const api = capture && capture.api;
  const senderUrl = sender && sender.tab && sender.tab.url;
  const policy = globalThis.AgentXConnectorPlatformPolicy;
  if (!api || !senderUrl || !policy || !policy.isReadOnlyCaptureMethod(api.method)) {
    return false;
  }

  let pageUrl;
  let apiUrl;
  try {
    pageUrl = new URL(senderUrl);
    apiUrl = new URL(String(api.url || ""));
  } catch (_error) {
    return false;
  }

  if (containsSensitiveFields(capture.data)) {
    return false;
  }

  const platform = policy.findPlatformByPageHost(pageUrl.hostname);
  if (platform && policy.matchesApiRule(platform, { ...api, url: apiUrl.href })) {
    return true;
  }

  if (!hasActiveGenericCapture(sender.tab.id)) {
    return false;
  }
  if (api.matched_rule === "generic-web-page") {
    return policy.isPageCaptureAllowed(pageUrl) &&
      pageUrl.origin === apiUrl.origin && pageUrl.pathname === apiUrl.pathname;
  }
  if (api.matched_rule === "generic-api-capture") {
    return policy.matchesGenericApiRule(pageUrl, { ...api, url: apiUrl.href });
  }
  return false;
}

function hasActiveGenericCapture(tabId) {
  const expiresAt = genericCaptureExpiries.get(tabId);
  if (!expiresAt || expiresAt < Date.now()) {
    genericCaptureExpiries.delete(tabId);
    return false;
  }
  return true;
}

function containsSensitiveFields(value) {
  if (Array.isArray(value)) {
    return value.some((item) => containsSensitiveFields(item));
  }
  if (!value || typeof value !== "object") {
    return false;
  }
  return Object.entries(value).some(([key, child]) =>
    isSensitiveKey(key) || containsSensitiveFields(child)
  );
}

function normalizeStructuredData(data, depth = 0) {
  if (depth > MAX_CAPTURE_DEPTH) {
    return "[MaxDepth]";
  }
  if (data == null || typeof data === "number" || typeof data === "boolean") {
    return data;
  }
  if (typeof data === "string") {
    return sanitizeCaptureText(data);
  }
  if (Array.isArray(data)) {
    return data.slice(0, MAX_CAPTURE_ARRAY_ITEMS).map((item) => normalizeStructuredData(item, depth + 1));
  }
  if (typeof data === "object") {
    const result = {};
    Object.keys(data)
      .slice(0, MAX_CAPTURE_OBJECT_KEYS)
      .forEach((key) => {
        if (!isSensitiveKey(key)) {
          result[key] = normalizeStructuredData(data[key], depth + 1);
        }
      });
    return result;
  }
  return null;
}

function sanitizeCaptureText(value) {
  const text = String(value || "")
    .replace(EMAIL_LIKE_PATTERN, "[REDACTED_EMAIL]")
    .replace(PHONE_LIKE_PATTERN, "[REDACTED_PHONE]")
    .replace(CARD_LIKE_PATTERN, "[REDACTED_CARD]")
    .replace(TOKEN_LIKE_PATTERN, "[REDACTED_TOKEN]");
  return text.length > 20000 ? `${text.slice(0, 20000)}...[truncated]` : text;
}

function isSensitiveKey(key) {
  return SENSITIVE_KEY_PATTERN.test(String(key || ""));
}

function normalizeSettings(rawSettings) {
  const original = { ...DEFAULT_SETTINGS, ...(rawSettings || {}) };
  const endpointCheck = validateEndpoint(original.endpoint);
  if (!endpointCheck.ok) {
    return { settings: original, endpointCheck, changed: false };
  }

  const settings = { ...original, endpoint: endpointCheck.endpoint };
  return {
    settings,
    endpointCheck,
    changed:
      original.endpoint !== settings.endpoint ||
      original.enabled !== settings.enabled
  };
}

async function rememberCaptureJob(rawJob) {
  await ensureCaptureJobsLoaded();
  const job = normalizeCaptureJob(rawJob);
  if (!job) return null;
  captureJobs.set(job.id, job);
  activeCaptureJobId = job.id;
  await persistCaptureJobs();
  return job;
}

async function getCaptureJobsForPopup() {
  await ensureCaptureJobsLoaded();
  await pruneExpiredCaptureJobs();
  if (!(await getActiveCaptureJob())) {
    await requestCaptureJobsFromAgentXTab();
  }
  await pruneExpiredCaptureJobs();
  return {
    ok: true,
    activeCaptureJobId,
    captureJobs: Array.from(captureJobs.values()).map(captureJobSummary)
  };
}

async function requestCaptureJobsFromAgentXTab() {
  if (!chrome.tabs || !chrome.tabs.query || !chrome.tabs.sendMessage) return;
  const tabs = await chrome.tabs.query({});
  for (const tab of tabs) {
    if (!tab || !Number.isInteger(tab.id) || !tab.url || !isAgentXAppPage(tab.url)) continue;
    try {
      const result = await chrome.tabs.sendMessage(tab.id, { type: "AGENTX_CONNECTOR_GET_CAPTURE_JOB" });
      if (result && result.captureJob) await rememberCaptureJob(result.captureJob);
    } catch (_error) {
      // Tabs without the connector content script are ignored.
    }
  }
}

async function getActiveCaptureJob() {
  await ensureCaptureJobsLoaded();
  await pruneExpiredCaptureJobs();
  return activeCaptureJobId ? captureJobs.get(activeCaptureJobId) || null : null;
}

async function selectCaptureJob(id) {
  await ensureCaptureJobsLoaded();
  activeCaptureJobId = captureJobs.has(id) ? id : null;
  await persistCaptureJobs();
}

async function ensureCaptureJobsLoaded() {
  if (captureJobsLoaded) return;
  if (!captureJobsLoadPromise) {
    captureJobsLoadPromise = chrome.storage.session
      .get([CAPTURE_JOBS_SESSION_KEY, ACTIVE_CAPTURE_JOB_SESSION_KEY])
      .then(async (stored) => {
        const savedJobs = Array.isArray(stored[CAPTURE_JOBS_SESSION_KEY])
          ? stored[CAPTURE_JOBS_SESSION_KEY]
          : [];
        for (const rawJob of savedJobs) {
          const job = normalizeCaptureJob(rawJob);
          if (job) captureJobs.set(job.id, job);
        }
        const savedActiveId = Number(stored[ACTIVE_CAPTURE_JOB_SESSION_KEY]);
        activeCaptureJobId = captureJobs.has(savedActiveId) ? savedActiveId : null;
        captureJobsLoaded = true;
        await pruneExpiredCaptureJobs();
      })
      .finally(() => {
        captureJobsLoadPromise = null;
      });
  }
  await captureJobsLoadPromise;
}

async function persistCaptureJobs() {
  await chrome.storage.session.set({
    [CAPTURE_JOBS_SESSION_KEY]: Array.from(captureJobs.values()),
    [ACTIVE_CAPTURE_JOB_SESSION_KEY]: activeCaptureJobId
  });
}

async function pruneExpiredCaptureJobs() {
  const now = Date.now();
  let changed = false;
  for (const [id, job] of captureJobs.entries()) {
    const expiresAt = Date.parse(job.ticket_expires_at || job.expires_at || "");
    if (!Number.isFinite(expiresAt) || expiresAt <= now) {
      captureJobs.delete(id);
      if (activeCaptureJobId === id) activeCaptureJobId = null;
      changed = true;
    }
  }
  if (changed) await persistCaptureJobs();
}

function normalizeCaptureJob(rawJob) {
  if (!rawJob || typeof rawJob !== "object") return null;
  const id = Number(rawJob.id);
  const ticket = String(rawJob.capability_ticket || "").trim();
  const targetHost = String(rawJob.target_host || "").toLowerCase();
  const targetPathPrefix = String(rawJob.target_path_prefix || "/");
  const expiresAt = Date.parse(rawJob.expires_at || "");
  const ticketExpiresAt = Date.parse(rawJob.ticket_expires_at || rawJob.expires_at || "");
  if (!Number.isInteger(id) || id < 1 || !ticket || !targetHost || !Number.isFinite(expiresAt) || !Number.isFinite(ticketExpiresAt) || ticketExpiresAt <= Date.now()) {
    return null;
  }
  return {
    id,
    purpose: String(rawJob.purpose || "generic_evidence"),
    target_host: targetHost,
    target_path_prefix: targetPathPrefix,
    expires_at: rawJob.expires_at,
    ticket_expires_at: rawJob.ticket_expires_at || rawJob.expires_at,
    capability_ticket: ticket
  };
}

function captureJobSummary(job) {
  return {
    id: job.id,
    purpose: job.purpose,
    target_host: job.target_host,
    target_path_prefix: job.target_path_prefix,
    expires_at: job.expires_at,
    ticket_expires_at: job.ticket_expires_at
  };
}

function captureMatchesJob(capture, sender, job) {
  try {
    const pageUrl = new URL((sender && sender.tab && sender.tab.url) || capture.page.url);
    return pageUrl.protocol === "https:" &&
      pageUrl.hostname.toLowerCase() === job.target_host &&
      pageUrl.pathname.startsWith(job.target_path_prefix);
  } catch (_error) {
    return false;
  }
}

function normalizeEndpointInput(endpoint) {
  const value = String(endpoint || "").trim();
  if (!value) {
    throw new Error("endpoint is required");
  }
  const parsed = new URL(value);
  if (parsed.pathname === "/" && !parsed.search && !parsed.hash) {
    parsed.pathname = INGEST_PATH;
  }
  return parsed;
}

function isTrustedAgentXEndpoint(parsedEndpoint) {
  return parsedEndpoint.protocol === "https:" &&
    AGENTX_VERCEL_HOST_PATTERN.test(parsedEndpoint.hostname);
}

async function synchronizeEndpointFromAgentXTab(sender) {
  let tab = sender && sender.tab && isAgentXAppPage(sender.tab.url) ? sender.tab : null;
  if (!tab) {
    const tabs = await chrome.tabs.query({});
    tab = tabs.find((item) => item && isAgentXAppPage(item.url)) || null;
  }
  if (!tab || !tab.url) return null;

  const page = new URL(tab.url);
  const endpoint = new URL(INGEST_PATH, page.origin).href;
  const parsedEndpoint = new URL(endpoint);
  if (!isTrustedAgentXEndpoint(parsedEndpoint)) return null;

  const stored = await chrome.storage.local.get(["settings"]);
  const settings = { ...DEFAULT_SETTINGS, ...(stored.settings || {}) };
  let current = null;
  try {
    current = settings.endpoint ? new URL(settings.endpoint) : null;
  } catch (_error) {
    current = null;
  }
  if (current && !isTrustedAgentXEndpoint(current)) return null;
  if (settings.endpoint !== endpoint) {
    await chrome.storage.local.set({ settings: { ...settings, endpoint } });
  }
  return endpoint;
}

function endpointMatchesHostPermission(parsedEndpoint) {
  const manifest =
    chrome.runtime && chrome.runtime.getManifest ? chrome.runtime.getManifest() : {};
  const permissions = Array.isArray(manifest.host_permissions) ? manifest.host_permissions : [];
  return permissions.some((permission) => hostPermissionMatchesEndpoint(permission, parsedEndpoint));
}

function hostPermissionMatchesEndpoint(permission, parsedEndpoint) {
  if (permission === "<all_urls>" || permission === "https://*/*" || permission === "http://*/*") {
    return false;
  }

  try {
    const parsedPermission = new URL(String(permission).replace(/\*$/, ""));
    if (parsedPermission.protocol !== parsedEndpoint.protocol) {
      return false;
    }
    if (parsedPermission.hostname !== parsedEndpoint.hostname) {
      return false;
    }
    return !parsedPermission.port || parsedPermission.port === parsedEndpoint.port;
  } catch (_error) {
    return false;
  }
}

function isReadOnlyCaptureMethod(method) {
  const policy = globalThis.AgentXConnectorPlatformPolicy;
  return Boolean(policy && policy.isReadOnlyCaptureMethod(method));
}

function safeUrl(rawUrl) {
  try {
    const parsed = new URL(rawUrl);
    return `${parsed.origin}${parsed.pathname}`;
  } catch (_error) {
    return null;
  }
}

if (typeof globalThis !== "undefined" && globalThis.__AGENTX_CONNECTOR_TEST_ENABLE__) {
  globalThis.__AGENTX_CONNECTOR_TEST__ = {
    normalizeEndpointInput,
    validateEndpoint,
    normalizeSettings,
    endpointMatchesHostPermission,
    hostPermissionMatchesEndpoint,
    isReadOnlyCaptureMethod,
    isAllowedCapture,
    enableGenericCapture,
    captureCurrentPage,
    hasActiveGenericCapture,
    isAgentXAppPage,
    normalizeStructuredData,
    buildIngestPayload,
    rememberCaptureJob,
    getActiveCaptureJob,
    captureMatchesJob,
    captureJobSummary
  };
}
