const DEFAULT_SETTINGS = {
  enabled: true,
  endpoint: "http://localhost:8000/api/browser-connector/ingest"
};

const INGEST_PATH = "/api/browser-connector/ingest";
const LOCAL_DEV_HOSTS = new Set(["localhost", "127.0.0.1"]);

const enabledEl = document.getElementById("enabled");
const endpointEl = document.getElementById("endpoint");
const saveEl = document.getElementById("save");
const statusBadgeEl = document.getElementById("statusBadge");
const queuedCountEl = document.getElementById("queuedCount");
const lastStatusEl = document.getElementById("lastStatus");

document.addEventListener("DOMContentLoaded", loadState);
saveEl.addEventListener("click", saveSettings);

async function loadState() {
  const state = await chrome.storage.local.get(["settings", "deliveries", "lastDelivery"]);
  const settings = { ...DEFAULT_SETTINGS, ...(state.settings || {}) };
  enabledEl.checked = Boolean(settings.enabled);
  endpointEl.value = settings.endpoint || DEFAULT_SETTINGS.endpoint;
  renderStatus(settings, state.deliveries || [], state.lastDelivery || null);
}

async function saveSettings() {
  const endpointCheck = validateEndpoint(endpointEl.value);
  if (!endpointCheck.ok) {
    renderStatus(
      { enabled: enabledEl.checked, endpoint: DEFAULT_SETTINGS.endpoint },
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
  renderStatus(settings, [], null);
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
      lastDelivery.reason === "invalid_endpoint" ? "Invalid endpoint" : "Skipped";
    return;
  }

  if (lastDelivery.ok) {
    lastStatusEl.textContent = lastDelivery.status ? `HTTP ${lastDelivery.status}` : "OK";
    return;
  }

  lastStatusEl.textContent = lastDelivery.status ? `HTTP ${lastDelivery.status}` : "Error";
}

function validateEndpoint(endpoint) {
  const value = String(endpoint || "").trim() || DEFAULT_SETTINGS.endpoint;
  let parsed;
  try {
    parsed = new URL(value);
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
  if (!endpointMatchesHostPermission(parsed)) {
    return { ok: false, error: "Endpoint origin is not granted by the extension manifest" };
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
