(function installAgentXConnectorHook() {
  if (window.__AGENTX_CONNECTOR_INJECTED__) {
    return;
  }
  window.__AGENTX_CONNECTOR_INJECTED__ = true;

  const CONNECTOR_MESSAGE_TYPE = "AGENTX_CONNECTOR_CAPTURE";
  const GENERIC_CAPTURE_ENABLE_EVENT = "agentx-browser-connector-enable-generic-api";
  const MAX_TEXT_LENGTH = 20000;
  const MAX_ARRAY_ITEMS = 50;
  const MAX_OBJECT_KEYS = 100;
  const MAX_DEPTH = 6;
  const MAX_GENERIC_API_CAPTURES = 10;
  const GENERIC_CAPTURE_WINDOW_MS = 60_000;
  const READONLY_CAPTURE_METHODS = new Set(["GET", "HEAD"]);
  const CAPTURE_POLICY_ATTRIBUTE = "data-agentx-connector-capture-policy";
  const ALLOWLIST = readCapturePolicy();
  const SENSITIVE_KEY_PATTERN = /(^|_|-)(authorization|auth|cookie|token|access_token|refresh_token|password|passwd|pwd|secret|captcha|verification|verify_code|sms_code|otp|payment|pay_password|card|cvv|credential|session|id_card|identity|email|e_mail|mail|phone|mobile|telephone|wechat|weixin|wx_id|qq|address)(_|-|$)/i;
  const EMAIL_LIKE_PATTERN = /\b[^\s@]+@[^\s@]+\.[^\s@]+\b/g;
  const PHONE_LIKE_PATTERN = /\b(?:\+?86[-\s]?)?1[3-9]\d{9}\b/g;
  const CARD_LIKE_PATTERN = /\b(?:\d[ -]*?){13,19}\b/g;
  const TOKEN_LIKE_PATTERN = /\b(?:[A-Za-z0-9_-]+\.){2}[A-Za-z0-9_-]+\b|\b[A-Za-z0-9._~-]{64,}\b/g;
  const BLOCKED_PATH_TOKENS = new Set([
    "login", "password", "auth", "token", "oauth", "callback", "captcha", "verify", "security",
    "payment", "pay", "wallet", "billing", "invoice", "order", "trade", "message", "chat", "im",
    "private", "address"
  ]);
  const PREFIX_BLOCKED_PATH_TOKENS = new Set(["message", "order", "trade", "payment", "invoice", "wallet", "billing"]);
  const SENSITIVE_QUERY_KEY_PATTERN = /authorization|auth|cookie|token|password|secret|session|credential|code|captcha|verify|payment/i;
  let genericCaptureUntil = 0;
  let genericCaptureCount = 0;

  window.addEventListener(GENERIC_CAPTURE_ENABLE_EVENT, () => {
    genericCaptureUntil = Date.now() + GENERIC_CAPTURE_WINDOW_MS;
    genericCaptureCount = 0;
  });

  patchFetch();
  patchXMLHttpRequest();

  function patchFetch() {
    if (typeof window.fetch !== "function") {
      return;
    }

    const originalFetch = window.fetch;
    window.fetch = async function agentXFetchHook(input, init) {
      const requestInfo = normalizeFetchInput(input, init);
      const response = await originalFetch.apply(this, arguments);
      const matchedRule = requestInfo && isReadOnlyCaptureMethod(requestInfo.method)
        ? findMatchingRule(requestInfo.url)
        : null;
      if (matchedRule && canCaptureResponse(matchedRule, response)) {
        captureFetchResponse(requestInfo, response.clone(), matchedRule);
      }
      return response;
    };
  }

  function patchXMLHttpRequest() {
    const proto = window.XMLHttpRequest && window.XMLHttpRequest.prototype;
    if (!proto || proto.__AGENTX_CONNECTOR_PATCHED__) {
      return;
    }

    const originalOpen = proto.open;
    const originalSend = proto.send;

    proto.open = function agentXXhrOpen(method, url) {
      this.__agentxConnector = {
        method: String(method || "GET").toUpperCase(),
        url: toAbsoluteUrl(url)
      };
      return originalOpen.apply(this, arguments);
    };

    proto.send = function agentXXhrSend() {
      const meta = this.__agentxConnector;
      const matchedRule = meta && isReadOnlyCaptureMethod(meta.method) ? findMatchingRule(meta.url) : null;
      if (meta && matchedRule) {
        meta.matchedRule = matchedRule;
        this.addEventListener("loadend", () => {
          if (canCaptureResponse(matchedRule, this)) {
            captureXhrResponse(this, meta);
          }
        });
      }
      return originalSend.apply(this, arguments);
    };

    proto.__AGENTX_CONNECTOR_PATCHED__ = true;
  }

  async function captureFetchResponse(requestInfo, response, matchedRule) {
    try {
      const contentType = response.headers && response.headers.get ? response.headers.get("content-type") || "" : "";
      const parsed = await readResponseBody(response, contentType);
      postCapture({
        api: buildApiMeta(requestInfo.url, requestInfo.method, response.status, contentType, matchedRule, "fetch"),
        data: parsed
      });
    } catch (_error) {
      // Capture failures must not change page behavior.
    }
  }

  function captureXhrResponse(xhr, meta) {
    try {
      const contentType = xhr.getResponseHeader ? xhr.getResponseHeader("content-type") || "" : "";
      const parsed = readXhrBody(xhr, contentType);
      postCapture({
        api: buildApiMeta(meta.url, meta.method, xhr.status, contentType, meta.matchedRule, "xmlhttprequest"),
        data: parsed
      });
    } catch (_error) {
      // Capture failures must not change page behavior.
    }
  }

  function canCaptureResponse(matchedRule, response) {
    if (!matchedRule || !matchedRule.generic) {
      return true;
    }
    const status = Number(response && response.status) || 0;
    const contentType = response && response.headers && response.headers.get
      ? response.headers.get("content-type") || ""
      : response && response.getResponseHeader ? response.getResponseHeader("content-type") || "" : "";
    if (!isGenericCaptureActive() || genericCaptureCount >= MAX_GENERIC_API_CAPTURES || status < 200 || status >= 300) {
      return false;
    }
    if (!isGenericApiContentType(contentType)) {
      return false;
    }
    genericCaptureCount += 1;
    return true;
  }

  function postCapture(payload) {
    window.postMessage(
      {
        type: CONNECTOR_MESSAGE_TYPE,
        payload: {
          captured_at: new Date().toISOString(),
          page: {
            url: safeUrl(window.location.href),
            title: sanitizeText(document.title || ""),
            referrer: safeUrl(document.referrer)
          },
          ...payload
        }
      },
      window.location.origin
    );
  }

  function normalizeFetchInput(input, init) {
    try {
      const url = input && typeof input === "object" && "url" in input ? input.url : input;
      const method = (init && init.method) ||
        (input && typeof input === "object" && "method" in input ? input.method : null) || "GET";
      return { url: toAbsoluteUrl(url), method: String(method).toUpperCase() };
    } catch (_error) {
      return null;
    }
  }

  function findMatchingRule(rawUrl) {
    const parsed = parseUrl(rawUrl);
    if (!parsed || isBlockedUrl(parsed) || hasSensitiveQuery(parsed)) {
      return null;
    }
    const exactRule = ALLOWLIST.find((item) =>
      item.host === parsed.hostname && item.pathPrefixes.some((prefix) => parsed.pathname.startsWith(prefix))
    );
    if (exactRule) {
      return exactRule;
    }
    if (isGenericCaptureActive() && parsed.origin === window.location.origin) {
      return { name: "generic-api-capture", generic: true };
    }
    return null;
  }

  function isGenericCaptureActive() {
    return Date.now() <= Math.max(
      genericCaptureUntil,
      Number(window.__AGENTX_CONNECTOR_GENERIC_CAPTURE_UNTIL__) || 0
    );
  }

  function isGenericApiContentType(contentType) {
    const normalized = String(contentType || "").toLowerCase();
    return normalized.includes("json") || normalized.startsWith("text/plain");
  }

  function isBlockedUrl(parsedUrl) {
    const tokens = parsedUrl.pathname.toLowerCase().split(/[\\/._-]+/).filter(Boolean);
    return tokens.some((token) => BLOCKED_PATH_TOKENS.has(token) || [...PREFIX_BLOCKED_PATH_TOKENS].some((blocked) => token.startsWith(blocked)));
  }

  function hasSensitiveQuery(parsedUrl) {
    return [...parsedUrl.searchParams.keys()].some((key) => SENSITIVE_QUERY_KEY_PATTERN.test(key));
  }

  function buildApiMeta(rawUrl, method, status, contentType, matchedRule, capturedFrom) {
    const parsed = parseUrl(rawUrl);
    const statusCode = Number(status) || 0;
    return {
      url: parsed ? safeUrl(parsed.href) : String(rawUrl || ""),
      method: String(method || "GET").toUpperCase(),
      status_code: statusCode >= 100 && statusCode <= 599 ? statusCode : null,
      matched_rule: matchedRule && matchedRule.name ? matchedRule.name : "allowlisted-api",
      response_mime: String(contentType || "").split(";")[0].trim().toLowerCase() || null,
      captured_from: capturedFrom
    };
  }

  async function readResponseBody(response, contentType) {
    if (isJsonContent(contentType)) {
      try {
        return { kind: "json", value: sanitizeValue(await response.json(), 0) };
      } catch (_error) {
        return { kind: "text", value: sanitizeText(await response.text()) };
      }
    }
    if (isTextContent(contentType)) {
      return { kind: "text", value: sanitizeText(await response.text()) };
    }
    return { kind: "unsupported", value: null };
  }

  function readXhrBody(xhr, contentType) {
    const responseType = xhr.responseType || "text";
    if (responseType !== "text" && responseType !== "") {
      return { kind: "unsupported", value: null };
    }
    const text = String(xhr.responseText || "");
    if (isJsonContent(contentType)) {
      try {
        return { kind: "json", value: sanitizeValue(JSON.parse(text), 0) };
      } catch (_error) {
        return { kind: "text", value: sanitizeText(text) };
      }
    }
    if (isTextContent(contentType)) {
      return { kind: "text", value: sanitizeText(text) };
    }
    return { kind: "unsupported", value: null };
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
        if (!isSensitiveKey(key)) {
          result[key] = sanitizeValue(value[key], depth + 1);
        }
      });
      return result;
    }
    return null;
  }

  function sanitizeText(text) {
    const value = String(text || "")
      .replace(EMAIL_LIKE_PATTERN, "[REDACTED_EMAIL]")
      .replace(PHONE_LIKE_PATTERN, "[REDACTED_PHONE]")
      .replace(CARD_LIKE_PATTERN, "[REDACTED_CARD]")
      .replace(TOKEN_LIKE_PATTERN, "[REDACTED_TOKEN]");
    return value.length > MAX_TEXT_LENGTH
      ? `${value.slice(0, MAX_TEXT_LENGTH)}...[truncated ${value.length - MAX_TEXT_LENGTH} chars]`
      : value;
  }

  function safeUrl(rawUrl) {
    const parsed = parseUrl(rawUrl);
    return parsed ? `${parsed.origin}${parsed.pathname}` : null;
  }

  function isJsonContent(contentType) {
    return String(contentType || "").toLowerCase().includes("json");
  }

  function isTextContent(contentType) {
    const normalized = String(contentType || "").toLowerCase();
    return normalized.startsWith("text/") || normalized.includes("javascript");
  }

  function isSensitiveKey(key) {
    return SENSITIVE_KEY_PATTERN.test(String(key || ""));
  }

  function readCapturePolicy() {
    try {
      const raw = document.documentElement.getAttribute(CAPTURE_POLICY_ATTRIBUTE);
      const parsed = JSON.parse(raw || "{}");
      return Array.isArray(parsed.apiRules) ? parsed.apiRules : [];
    } catch (_error) {
      return [];
    }
  }

  function isReadOnlyCaptureMethod(method) {
    return READONLY_CAPTURE_METHODS.has(String(method || "").toUpperCase());
  }

  function toAbsoluteUrl(url) {
    return new URL(String(url), window.location.href).href;
  }

  function parseUrl(rawUrl) {
    try {
      return new URL(String(rawUrl), window.location.href);
    } catch (_error) {
      return null;
    }
  }
})();
