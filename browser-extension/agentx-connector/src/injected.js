(function installAgentXConnectorHook() {
  if (window.__AGENTX_CONNECTOR_INJECTED__) {
    return;
  }
  window.__AGENTX_CONNECTOR_INJECTED__ = true;

  const CONNECTOR_MESSAGE_TYPE = "AGENTX_CONNECTOR_CAPTURE";
  const MAX_TEXT_LENGTH = 20000;
  const MAX_ARRAY_ITEMS = 50;
  const MAX_OBJECT_KEYS = 100;
  const MAX_DEPTH = 6;
  const READONLY_CAPTURE_METHODS = new Set(["GET", "HEAD"]);

  const ALLOWLIST = [
    {
      name: "buyin-api",
      host: "buyin.jinritemai.com",
      pathPrefixes: ["/api/", "/aweme/v1/", "/dashboard/api/", "/mpa/api/", "/square_pc_api/", "/creative_radar_api/", "/apply_sample_pc_api/"]
    },
    {
      name: "compass-api",
      host: "compass.jinritemai.com",
      pathPrefixes: ["/api/", "/compass_api/", "/compass/"]
    },
    {
      name: "fxg-api",
      host: "fxg.jinritemai.com",
      pathPrefixes: ["/api/", "/ffa/api/"]
    },
    {
      name: "douyin-web-api",
      host: "www.douyin.com",
      pathPrefixes: ["/aweme/v1/web/", "/api/"]
    },
    {
      name: "xqttool-api",
      host: "xqttool.com",
      pathPrefixes: ["/api/"]
    },
    {
      name: "xqttool-www-api",
      host: "www.xqttool.com",
      pathPrefixes: ["/api/"]
    },
    {
      name: "oceanengine-api",
      host: "cc.oceanengine.com",
      pathPrefixes: ["/api/", "/open_api/"]
    }
  ];

  const SENSITIVE_KEY_PATTERN = /(^|_|-)(authorization|auth|cookie|token|access_token|refresh_token|password|passwd|pwd|secret|captcha|verification|verify_code|sms_code|otp|payment|pay_password|card|cvv|credential|session|id_card)(_|-|$)/i;
  const TOKEN_LIKE_PATTERN = /^([A-Za-z0-9_-]+\.){2}[A-Za-z0-9_-]+$|^[A-Za-z0-9._~-]{64,}$/;
  const CARD_LIKE_PATTERN = /\b(?:\d[ -]*?){13,19}\b/;

  patchFetch();
  patchXMLHttpRequest();

  function patchFetch() {
    if (typeof window.fetch !== "function") {
      return;
    }

    const originalFetch = window.fetch;
    window.fetch = async function agentXFetchHook(input, init) {
      const requestInfo = normalizeFetchInput(input, init);
      const startedAt = performance.now();
      const response = await originalFetch.apply(this, arguments);

      const matchedRule =
        requestInfo && isReadOnlyCaptureMethod(requestInfo.method)
          ? findMatchingRule(requestInfo.url)
          : null;
      if (matchedRule) {
        captureFetchResponse(requestInfo, response.clone(), startedAt, matchedRule);
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
      const matchedRule =
        meta && isReadOnlyCaptureMethod(meta.method) ? findMatchingRule(meta.url) : null;
      if (meta && matchedRule) {
        meta.startedAt = performance.now();
        meta.matchedRule = matchedRule;
        this.addEventListener("loadend", () => captureXhrResponse(this, meta));
      }
      return originalSend.apply(this, arguments);
    };

    proto.__AGENTX_CONNECTOR_PATCHED__ = true;
  }

  async function captureFetchResponse(requestInfo, response, startedAt, matchedRule) {
    try {
      const contentType = response.headers && response.headers.get ? response.headers.get("content-type") || "" : "";
      const parsed = await readResponseBody(response, contentType);
      postCapture({
        api: buildApiMeta(requestInfo.url, requestInfo.method, response.status, contentType, matchedRule, "fetch"),
        data: parsed
      });
    } catch (_error) {
      // Capture failures must not change platform page behavior.
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
      // Capture failures must not change platform page behavior.
    }
  }

  function postCapture(payload) {
    window.postMessage(
      {
        type: CONNECTOR_MESSAGE_TYPE,
        payload: {
          captured_at: new Date().toISOString(),
          page: {
            url: safeUrl(window.location.href),
            title: document.title || null,
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
      const method =
        (init && init.method) ||
        (input && typeof input === "object" && "method" in input ? input.method : null) ||
        "GET";
      return {
        url: toAbsoluteUrl(url),
        method: String(method).toUpperCase()
      };
    } catch (_error) {
      return null;
    }
  }

  function findMatchingRule(rawUrl) {
    const parsed = parseUrl(rawUrl);
    if (!parsed) {
      return null;
    }

    const rule = ALLOWLIST.find((item) => item.host === parsed.hostname);
    if (!rule) {
      return null;
    }

    return rule.pathPrefixes.some((prefix) => parsed.pathname.startsWith(prefix)) ? rule : null;
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
        return {
          kind: "json",
          value: sanitizeValue(await response.json(), 0)
        };
      } catch (_error) {
        return {
          kind: "text",
          value: sanitizeText(await response.text())
        };
      }
    }

    if (isTextContent(contentType)) {
      return {
        kind: "text",
        value: sanitizeText(await response.text())
      };
    }

    return {
      kind: "unsupported",
      value: null
    };
  }

  function readXhrBody(xhr, contentType) {
    const responseType = xhr.responseType || "text";
    if (responseType !== "text" && responseType !== "") {
      return {
        kind: "unsupported",
        value: null
      };
    }

    const text = String(xhr.responseText || "");
    if (isJsonContent(contentType)) {
      try {
        return {
          kind: "json",
          value: sanitizeValue(JSON.parse(text), 0)
        };
      } catch (_error) {
        return {
          kind: "text",
          value: sanitizeText(text)
        };
      }
    }

    if (isTextContent(contentType)) {
      return {
        kind: "text",
        value: sanitizeText(text)
      };
    }

    return {
      kind: "unsupported",
      value: null
    };
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
      Object.keys(value)
        .slice(0, MAX_OBJECT_KEYS)
        .forEach((key) => {
          if (isSensitiveKey(key)) {
            result[key] = "[REDACTED]";
          } else {
            result[key] = sanitizeValue(value[key], depth + 1);
          }
        });
      return result;
    }

    return null;
  }

  function sanitizeText(text) {
    const value = String(text || "");
    if (!value) {
      return value;
    }

    if (TOKEN_LIKE_PATTERN.test(value) || CARD_LIKE_PATTERN.test(value)) {
      return "[REDACTED]";
    }

    if (value.length > MAX_TEXT_LENGTH) {
      return `${value.slice(0, MAX_TEXT_LENGTH)}...[truncated ${value.length - MAX_TEXT_LENGTH} chars]`;
    }

    return value;
  }

  function safeUrl(rawUrl) {
    const parsed = parseUrl(rawUrl);
    if (!parsed) {
      return null;
    }
    return `${parsed.origin}${parsed.pathname}`;
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
