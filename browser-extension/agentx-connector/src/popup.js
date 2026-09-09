const DEFAULT_SETTINGS = {
  enabled: true,
  endpoint: ""
};

const INGEST_PATH = "/api/browser-connector/ingest";
const LOCAL_DEV_HOSTS = new Set(["localhost", "127.0.0.1"]);
const AGENTX_VERCEL_HOST_PATTERN = /^agentx(?:-[a-z0-9-]+)?-dyx8888s-projects\.vercel\.app$/i;

const enabledEl = document.getElementById("enabled");
const endpointEl = document.getElementById("endpoint");
const saveEl = document.getElementById("save");
const captureCurrentPageEl = document.getElementById("captureCurrentPage");
const captureJobEl = document.getElementById("captureJob");
const captureJobHintEl = document.getElementById("captureJobHint");
const statusBadgeEl = document.getElementById("statusBadge");
const queuedCountEl = document.getElementById("queuedCount");
const lastStatusEl = document.getElementById("lastStatus");

document.addEventListener("DOMContentLoaded", async () => {
  await chrome.runtime.sendMessage({ type: "AGENTX_CONNECTOR_SYNC_ENDPOINT" }).catch(() => {});
  await loadState();
  await loadCaptureJobs();
});
saveEl.addEventListener("click", saveSettings);
captureCurrentPageEl.addEventListener("click", captureCurrentPage);
if (captureJobEl) captureJobEl.addEventListener("change", selectCaptureJob);

async function loadState() {
  const state = await chrome.storage.local.get(["settings", "deliveries", "lastDelivery"]);
  const { settings, endpointCheck, changed } = normalizeSettings(state.settings || {});
  if (changed) {
    await chrome.storage.local.set({ settings });
  }

  enabledEl.checked = Boolean(settings.enabled);
  renderEndpoint(settings.endpoint || "");
  renderStatus(
    settings,
    state.deliveries || [],
    endpointCheck.ok
      ? state.lastDelivery || null
      : {
          ok: false,
          skipped: true,
          reason: "invalid_endpoint",
          error: endpointCheck.error
        }
  );
}

async function saveSettings() {
  const endpointCheck = validateEndpoint(endpointEl.value);
  if (!endpointCheck.ok) {
    renderEndpoint(String(endpointEl.value || "").trim());
    renderStatus(
      { enabled: enabledEl.checked, endpoint: String(endpointEl.value || "").trim() },
      [],
      {
        ok: false,
        skipped: true,
        reason: "invalid_endpoint",
        error: endpointCheck.error
      }
    );
    return;
  }

  const settings = {
    enabled: enabledEl.checked,
    endpoint: endpointCheck.endpoint
  };
  await chrome.storage.local.set({ settings });
  renderEndpoint(settings.endpoint);
  renderStatus(settings, [], { ok: true, skipped: true, reason: "settings_saved" });
}

async function captureCurrentPage() {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab || !Number.isInteger(tab.id)) {
      lastStatusEl.textContent = "No active page";
      return;
    }

    const enabled = await chrome.runtime.sendMessage({
      type: "AGENTX_CONNECTOR_ENABLE_GENERIC_CAPTURE",
      tabId: tab.id
    });
    if (!enabled || !enabled.ok) {
      lastStatusEl.textContent = "Blocked page";
      return;
    }

    const capture = await chrome.runtime.sendMessage({
      type: "AGENTX_CONNECTOR_CAPTURE_CURRENT_PAGE",
      tabId: tab.id
    });
    const delivery = capture && capture.result && capture.result.delivery;
    lastStatusEl.textContent = delivery && delivery.status ? `HTTP ${delivery.status}` : "Capture started";
  } catch (_error) {
    lastStatusEl.textContent = "Unavailable";
  }
}

async function loadCaptureJobs() {
  try {
    const result = await chrome.runtime.sendMessage({ type: "AGENTX_CONNECTOR_GET_CAPTURE_JOBS" });
    renderCaptureJobs(result && result.captureJobs, result && result.activeCaptureJobId);
  } catch (_error) {
    renderCaptureJobs([], null);
  }
}

function renderCaptureJobs(jobs, activeId) {
  if (!captureJobEl) return;
  const entries = Array.isArray(jobs) ? jobs : [];
  captureJobEl.replaceChildren();
  const empty = document.createElement("option");
  empty.value = "";
  empty.textContent = "No task selected";
  captureJobEl.appendChild(empty);
  for (const job of entries) {
    const option = document.createElement("option");
    option.value = String(job.id);
    option.textContent = `#${job.id} ${job.purpose} - ${job.target_host}`;
    option.selected = Number(job.id) === Number(activeId);
    captureJobEl.appendChild(option);
  }
  captureJobEl.value = activeId ? String(activeId) : "";
  if (captureJobHintEl) {
    captureJobHintEl.textContent = entries.length
      ? "Task capability is session-only and expires automatically."
      : "Create a task in the current AgentX conversation first.";
  }
}

async function selectCaptureJob() {
  if (!captureJobEl) return;
  const rawId = captureJobEl.value;
  try {
    await chrome.runtime.sendMessage({
      type: "AGENTX_CONNECTOR_SELECT_CAPTURE_JOB",
      captureJobId: rawId ? Number(rawId) : null
    });
  } finally {
    await loadCaptureJobs();
  }
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

function renderEndpoint(endpoint) {
  endpointEl.value = endpoint;
  endpointEl.title = endpoint;
}

function renderStatus(settings, deliveries, lastDelivery) {
  statusBadgeEl.textContent = settings.enabled ? "Enabled" : "Disabled";
  statusBadgeEl.classList.toggle("on", settings.enabled);
  statusBadgeEl.classList.toggle("off", !settings.enabled);
  queuedCountEl.textContent = String(deliveries.length);

  if (!lastDelivery) {
    lastStatusEl.textContent = "None";
    return;
  }

  if (lastDelivery.skipped) {
    lastStatusEl.textContent =
      lastDelivery.reason === "invalid_endpoint"
        ? "Invalid endpoint"
        : lastDelivery.reason === "settings_saved"
          ? "Saved"
          : "Skipped";
    return;
  }

  if (lastDelivery.ok) {
    lastStatusEl.textContent = lastDelivery.status ? `HTTP ${lastDelivery.status}` : "OK";
    return;
  }

  lastStatusEl.textContent = lastDelivery.status ? `HTTP ${lastDelivery.status}` : "Error";
}

function validateEndpoint(endpoint) {
  let parsed;
  try {
    parsed = normalizeEndpointInput(endpoint);
  } catch (_error) {
    return { ok: false, error: "Endpoint must be a valid URL" };
  }

  if (parsed.username || parsed.password) {
    return { ok: false, error: "Endpoint must not contain URL credentials" };
  }
  if (parsed.search || parsed.hash) {
    return { ok: false, error: "Endpoint must not contain query strings or fragments" };
  }
  if (parsed.pathname !== INGEST_PATH) {
    return { ok: false, error: `Endpoint path must be ${INGEST_PATH}` };
  }

  const isLocalHttp =
    parsed.protocol === "http:" && LOCAL_DEV_HOSTS.has(parsed.hostname);
  const isHttps = parsed.protocol === "https:";
  if (!isLocalHttp && !isHttps) {
    return { ok: false, error: "Endpoint must use https, except local development hosts" };
  }
  if (!endpointMatchesHostPermission(parsed) && !isTrustedAgentXEndpoint(parsed)) {
    return { ok: false, error: "Endpoint origin is not granted by the extension manifest" };
  }

  return { ok: true, endpoint: parsed.href };
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

if (typeof globalThis !== "undefined" && globalThis.__AGENTX_CONNECTOR_TEST_ENABLE__) {
  globalThis.__AGENTX_CONNECTOR_POPUP_TEST__ = {
    normalizeEndpointInput,
    validateEndpoint,
    normalizeSettings,
    loadState,
    saveSettings,
    captureCurrentPage,
    renderCaptureJobs
  };
}
