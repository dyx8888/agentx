const DEFAULT_SETTINGS = {
  enabled: true,
  endpoint: "http://localhost:8000/api/browser-connector/ingest"
};

const MAX_LOG_ENTRIES = 50;
const INGEST_PATH = "/api/browser-connector/ingest";
const LOCAL_DEV_HOSTS = new Set(["localhost", "127.0.0.1"]);
const READONLY_CAPTURE_METHODS = new Set(["GET", "HEAD"]);

chrome.runtime.onInstalled.addListener(async () => {
  const existing = await chrome.storage.local.get(["settings"]);
  if (!existing.settings) {
    await chrome.storage.local.set({ settings: DEFAULT_SETTINGS, deliveries: [] });
  }
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || message.type !== "AGENTX_CONNECTOR_CAPTURE") {
    return false;
  }

  handleCapture(message.payload, sender)
    .then((result) => sendResponse({ ok: true, result }))
    .catch((error) => sendResponse({ ok: false, error: String(error && error.message ? error.message : error) }));

  return true;
});

async function handleCapture(capture, sender) {
  const { settings = DEFAULT_SETTINGS } = await chrome.storage.local.get(["settings"]);
  const effectiveSettings = { ...DEFAULT_SETTINGS, ...settings };

  if (!effectiveSettings.enabled) {
    return recordDelivery({
      ok: false,
      skipped: true,
      reason: "disabled",
      capturedAt: capture && capture.captured_at
    });
  }

  const deliveredAt = new Date().toISOString();
  const endpointCheck = validateEndpoint(effectiveSettings.endpoint);
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
  const payload = buildIngestPayload(capture, sender);

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

    return recordDelivery({
      ok: response.ok,
      status: response.status,
      endpoint,
      deliveredAt,
      apiUrl: payload.api && payload.api.url,
      matchedRule: payload.api && payload.api.matched_rule
    });
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

function buildIngestPayload(capture, sender) {
  const tabUrl = sender && sender.tab && sender.tab.url ? safeUrl(sender.tab.url) : null;
  const api = buildApiCaptureMetadata(capture && capture.api);
  const page = buildPageMetadata(capture && capture.page, tabUrl);

  return {
    connector: {
      source: "chrome-extension-mv3",
      extension_id: chrome.runtime && chrome.runtime.id ? chrome.runtime.id : null,
      version: "0.1.0",
      mode: "readonly"
    },
    captured_at: capture && capture.captured_at ? capture.captured_at : new Date().toISOString(),
    page,
    api,
    data: normalizeStructuredData(capture && capture.data),
    policy: {
      whitelist_rule: api.matched_rule,
      redaction_version: "v1",
      contains_credentials: false,
      contains_sensitive_fields: false,
      platform_write_operation: false
    }
  };
}

function buildPageMetadata(page, tabUrl) {
  return {
    url: page && page.url ? page.url : tabUrl || "about:blank",
    title: page && page.title ? String(page.title).slice(0, 300) : null,
    referrer: page && page.referrer ? page.referrer : null
  };
}

function buildApiCaptureMetadata(api) {
  const statusCode = Number(api && (api.status_code || api.status)) || 0;
  return {
    url: api && api.url ? api.url : "about:blank",
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

function normalizeStructuredData(data) {
  if (data && typeof data === "object") {
    return data;
  }
  return { kind: "unsupported", value: null };
}

async function recordDelivery(entry) {
  const existing = await chrome.storage.local.get(["deliveries"]);
  const deliveries = Array.isArray(existing.deliveries) ? existing.deliveries : [];
  const next = [entry, ...deliveries].slice(0, MAX_LOG_ENTRIES);
  await chrome.storage.local.set({ deliveries: next, lastDelivery: entry });
  return entry;
}

function validateEndpoint(endpoint) {
  const value = String(endpoint || "").trim() || DEFAULT_SETTINGS.endpoint;
  let parsed;
  try {
    parsed = new URL(value);
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
  if (!endpointMatchesHostPermission(parsed)) {
    return { ok: false, error: "endpoint origin is not granted by the extension manifest" };
  }

  return { ok: true, endpoint: parsed.href };
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
  return READONLY_CAPTURE_METHODS.has(String(method || "").toUpperCase());
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
    validateEndpoint,
    endpointMatchesHostPermission,
    hostPermissionMatchesEndpoint,
    isReadOnlyCaptureMethod,
    buildIngestPayload
  };
}
