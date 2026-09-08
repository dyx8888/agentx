(function bootstrapAgentXConnector() {
  if (window.__AGENTX_CONNECTOR_CONTENT_SCRIPT__) {
    return;
  }
  window.__AGENTX_CONNECTOR_CONTENT_SCRIPT__ = true;

  const CONNECTOR_STATUS_EVENT = "agentx-browser-connector-status";
  const CAPTURE_JOB_EVENT = "agentx-browser-connector-capture-job";
  const CONNECTOR_STATUS_STORAGE_KEY = "agentx_browser_connector_status";
  const CAPTURE_POLICY_ATTRIBUTE = "data-agentx-connector-capture-policy";
  const GENERIC_CAPTURE_ENABLE_EVENT = "agentx-browser-connector-enable-generic-api";
  const MAX_VISIBLE_TEXT_LENGTH = 8000;
  const MAX_HEADING_COUNT = 20;
  const MAX_META_ITEMS = 12;
  const MAX_JSON_LD_ITEMS = 10;
  const MAX_OBJECT_KEYS = 80;
  const MAX_ARRAY_ITEMS = 30;
  const MAX_DEPTH = 5;
  const SENSITIVE_KEY_PATTERN = /(^|_|-)(authorization|auth|cookie|token|access_token|refresh_token|password|passwd|pwd|secret|captcha|verification|verify_code|sms_code|otp|payment|pay_password|card|cvv|credential|session|id_card|identity|email|e_mail|mail|phone|mobile|telephone|wechat|weixin|wx_id|qq|address)(_|-|$)/i;
  const EMAIL_LIKE_PATTERN = /\b[^\s@]+@[^\s@]+\.[^\s@]+\b/g;
  const PHONE_LIKE_PATTERN = /\b(?:\+?86[-\s]?)?1[3-9]\d{9}\b/g;
  const CARD_LIKE_PATTERN = /\b(?:\d[ -]*?){13,19}\b/g;
  const TOKEN_LIKE_PATTERN = /\b(?:[A-Za-z0-9_-]+\.){2}[A-Za-z0-9_-]+\b|\b[A-Za-z0-9._~-]{64,}\b/g;
  const SAFE_META_NAMES = new Set([
    "description",
    "keywords",
    "application-name",
    "og:title",
    "og:description",
    "og:type",
    "twitter:title",
    "twitter:description",
    "article:section"
  ]);
  const AGENTX_APP_HOSTS = new Set([
    "localhost",
    "127.0.0.1",
    "agentx-fnbfc0d1r-dyx8888s-projects.vercel.app"
  ]);

  if (isAgentXAppPage()) {
    announceConnectorStatus();
    installCaptureJobBridge();
    return;
  }

  const policy = globalThis.AgentXConnectorPlatformPolicy;
  if (!policy || !policy.isPageCaptureAllowed(window.location.href)) {
    return;
  }

  const platform = policy.findPlatformByPageHost(window.location.hostname);
  setCapturePolicy(platform);
  const pageHookReady = injectPageHook();
  installMessageBridge(platform);
  installUserCaptureHandler();

  function isAgentXAppPage() {
    const hostname = window.location.hostname;
    return AGENTX_APP_HOSTS.has(hostname) || /^agentx-[a-z0-9-]+\.vercel\.app$/i.test(hostname);
  }

  function setCapturePolicy(currentPlatform) {
    const safePolicy = {
      id: currentPlatform ? currentPlatform.id : "generic",
      apiRules: currentPlatform ? currentPlatform.apiRules : []
    };
    document.documentElement.setAttribute(CAPTURE_POLICY_ATTRIBUTE, JSON.stringify(safePolicy));
  }

  function injectPageHook() {
    return new Promise((resolve) => {
      const script = document.createElement("script");
      script.src = chrome.runtime.getURL("src/injected.js");
      script.async = false;
      script.onload = () => {
        script.remove();
        document.documentElement.removeAttribute(CAPTURE_POLICY_ATTRIBUTE);
        resolve();
      };
      script.onerror = () => {
        script.remove();
        document.documentElement.removeAttribute(CAPTURE_POLICY_ATTRIBUTE);
        resolve();
      };
      (document.documentElement || document.head || document.body).appendChild(script);
    });
  }

  function installMessageBridge(currentPlatform) {
    window.addEventListener("message", async (event) => {
      if (event.source !== window || !event.data || event.data.type !== "AGENTX_CONNECTOR_CAPTURE") {
        return;
      }
      if (!isAllowedCapture(event.data.payload, currentPlatform)) {
        return;
      }

      try {
        await chrome.runtime.sendMessage({
          type: "AGENTX_CONNECTOR_CAPTURE",
          payload: event.data.payload
        });
      } catch (_error) {
        // The page hook must never break platform behavior if the worker is unavailable.
      }
    });
  }

  function installUserCaptureHandler() {
    chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
      if (!message || message.type !== "AGENTX_CONNECTOR_CAPTURE_CURRENT_PAGE") {
        return false;
      }

      captureCurrentPage()
        .then((result) => sendResponse({ ok: true, result }))
        .catch((error) => sendResponse({ ok: false, error: String(error && error.message ? error.message : error) }));
      return true;
    });
  }

  async function captureCurrentPage() {
    const capture = buildGenericPageCapture();
    if (!capture) {
      return { captured: false, reason: "blocked_page" };
    }

    await pageHookReady;
    window.dispatchEvent(new CustomEvent(GENERIC_CAPTURE_ENABLE_EVENT));
    return { captured: true, capture };
  }

  function buildGenericPageCapture() {
    if (!policy.isPageCaptureAllowed(window.location.href)) {
      return null;
    }

    const pageUrl = safeUrl(window.location.href);
    if (!pageUrl) {
      return null;
    }
    return {
      captured_at: new Date().toISOString(),
      page: {
        url: pageUrl,
        title: sanitizeText(document.title || ""),
        referrer: safeUrl(document.referrer)
      },
      api: {
        url: pageUrl,
        method: "GET",
        status_code: null,
        matched_rule: "generic-web-page",
        response_mime: "text/html",
        captured_from: "fetch"
      },
      data: {
        kind: "generic_web_page",
        title: sanitizeText(document.title || ""),
        headings: collectHeadings(),
        visible_text: sanitizeText(String((document.body || document.documentElement).innerText || "")).slice(0, MAX_VISIBLE_TEXT_LENGTH),
        meta: collectSafeMeta(),
        structured_data: collectJsonLd()
      }
    };
  }

  function collectHeadings() {
    return Array.from(document.querySelectorAll("h1, h2, h3"))
      .map((node) => sanitizeText(node.innerText || node.textContent || "").trim())
      .filter(Boolean)
      .slice(0, MAX_HEADING_COUNT);
  }

  function collectSafeMeta() {
    const result = {};
    for (const node of Array.from(document.querySelectorAll("meta[name], meta[property]"))) {
      const rawName = node.getAttribute("name") || node.getAttribute("property") || "";
      const name = rawName.trim().toLowerCase();
      if (!SAFE_META_NAMES.has(name) || Object.keys(result).length >= MAX_META_ITEMS) {
        continue;
      }
      const content = sanitizeText(node.getAttribute("content") || "").trim();
      if (content) {
        result[name] = content;
      }
    }
    return result;
  }

  function collectJsonLd() {
    const values = [];
    for (const node of Array.from(document.querySelectorAll('script[type="application/ld+json"]')).slice(0, MAX_JSON_LD_ITEMS)) {
      try {
        values.push(sanitizeValue(JSON.parse(node.textContent || "null"), 0));
      } catch (_error) {
        // Invalid structured data is not useful for the connector.
      }
    }
    return values;
  }

  function isAllowedCapture(capture, currentPlatform) {
    const api = capture && capture.api;
    if (!api || !policy.isReadOnlyCaptureMethod(api.method) || containsSensitiveFields(capture.data)) {
      return false;
    }
    if (currentPlatform && policy.matchesApiRule(currentPlatform, api)) {
      return true;
    }
    if (api.matched_rule === "generic-api-capture") {
      return policy.matchesGenericApiRule(window.location.href, api);
    }
    return false;
  }

  function containsSensitiveFields(value) {
    if (Array.isArray(value)) {
      return value.some((item) => containsSensitiveFields(item));
    }
    if (!value || typeof value !== "object") {
      return false;
    }
    return Object.entries(value).some(([key, child]) =>
      SENSITIVE_KEY_PATTERN.test(String(key)) || containsSensitiveFields(child)
    );
  }

  function sanitizeValue(value, depth) {
    if (depth > MAX_DEPTH) {
      return "[MaxDepth]";
    }
    if (value == null || typeof value === "number" || typeof value === "boolean") {
      return value;
    }
    if (typeof value === "string") {
      return sanitizeText(value);
    }
    if (Array.isArray(value)) {
      return value.slice(0, MAX_ARRAY_ITEMS).map((item) => sanitizeValue(item, depth + 1));
    }
    if (typeof value === "object") {
      const result = {};
      Object.keys(value).slice(0, MAX_OBJECT_KEYS).forEach((key) => {
        if (!SENSITIVE_KEY_PATTERN.test(key)) {
          result[key] = sanitizeValue(value[key], depth + 1);
        }
      });
      return result;
    }
    return null;
  }

  function sanitizeText(value) {
    return String(value || "")
      .replace(EMAIL_LIKE_PATTERN, "[REDACTED_EMAIL]")
      .replace(PHONE_LIKE_PATTERN, "[REDACTED_PHONE]")
      .replace(CARD_LIKE_PATTERN, "[REDACTED_CARD]")
      .replace(TOKEN_LIKE_PATTERN, "[REDACTED_TOKEN]");
  }

  function safeUrl(rawUrl) {
    try {
      const parsed = new URL(String(rawUrl || ""), window.location.href);
      return `${parsed.origin}${parsed.pathname}`;
    } catch (_error) {
      return null;
    }
  }

  function announceConnectorStatus() {
    try {
      window.localStorage.setItem(CONNECTOR_STATUS_STORAGE_KEY, "connected");
    } catch (_error) {
      // Status reporting must not affect the host page.
    }

    try {
      window.dispatchEvent(new Event(CONNECTOR_STATUS_EVENT));
    } catch (_error) {
      // Some isolated-world event constructors may be unavailable in tests.
    }
  }

  function installCaptureJobBridge() {
    let currentCaptureJob = null;
    window.addEventListener(CAPTURE_JOB_EVENT, async (event) => {
      const payload = normalizeCaptureJob(event && event.detail);
      if (!payload) return;
      currentCaptureJob = payload;
      try {
        await chrome.runtime.sendMessage({ type: "AGENTX_CONNECTOR_SET_CAPTURE_JOB", captureJob: payload });
      } catch (_error) {
        // The host page remains usable when the extension worker is asleep.
      }
    });
    chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
      if (!message || message.type !== "AGENTX_CONNECTOR_GET_CAPTURE_JOB") return false;
      sendResponse({ ok: true, captureJob: currentCaptureJob });
      return false;
    });
  }

  function normalizeCaptureJob(value) {
    if (!value || typeof value !== "object") return null;
    const job = value.job && typeof value.job === "object" ? value.job : value;
    const ticket = String(value.capability_ticket || "").trim();
    const id = Number(job.id);
    if (!Number.isInteger(id) || id < 1 || !ticket || job.status !== "pending") return null;
    return {
      id,
      purpose: String(job.purpose || "generic_evidence"),
      target_host: String(job.target_host || "").toLowerCase(),
      target_path_prefix: String(job.target_path_prefix || "/"),
      expires_at: job.expires_at || null,
      capability_ticket: ticket
    };
  }
})();
