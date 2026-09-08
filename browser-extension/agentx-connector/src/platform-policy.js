(function installAgentXConnectorPlatformPolicy() {
  const READONLY_CAPTURE_METHODS = new Set(["GET", "HEAD"]);
  const LOCAL_DEV_HOSTS = new Set(["localhost", "127.0.0.1"]);
  const BLOCKED_PATH_FRAGMENTS = new Set([
    "login",
    "password",
    "auth",
    "token",
    "oauth",
    "callback",
    "captcha",
    "verify",
    "security",
    "payment",
    "pay",
    "wallet",
    "billing",
    "invoice",
    "order",
    "trade",
    "message",
    "chat",
    "im",
    "private",
    "address"
  ]);
  const SENSITIVE_QUERY_KEY_PATTERN = /authorization|auth|cookie|token|password|secret|session|credential|code|captcha|verify|payment/i;
  const PREFIX_BLOCKED_PATH_TOKENS = new Set(["message", "order", "trade", "payment", "invoice", "wallet", "billing"]);

  const SUPPORTED_PLATFORMS = [
    {
      id: "buyin",
      pageHosts: ["buyin.jinritemai.com"],
      recordKinds: ["creator_profile", "knowledge_observation"],
      apiRules: [
        {
          name: "buyin-api",
          host: "buyin.jinritemai.com",
          pathPrefixes: ["/api/", "/aweme/v1/", "/dashboard/api/", "/mpa/api/", "/square_pc_api/", "/creative_radar_api/", "/apply_sample_pc_api/"]
        }
      ]
    },
    {
      id: "compass",
      pageHosts: ["compass.jinritemai.com"],
      recordKinds: ["creator_profile", "knowledge_observation"],
      apiRules: [
        {
          name: "compass-api",
          host: "compass.jinritemai.com",
          pathPrefixes: ["/api/", "/compass_api/", "/compass/"]
        }
      ]
    },
    {
      id: "fxg",
      pageHosts: ["fxg.jinritemai.com"],
      recordKinds: ["knowledge_observation"],
      apiRules: [
        {
          name: "fxg-api",
          host: "fxg.jinritemai.com",
          pathPrefixes: ["/api/", "/ffa/api/"]
        }
      ]
    },
    {
      id: "douyin",
      pageHosts: ["www.douyin.com", "creator.douyin.com"],
      recordKinds: ["creator_profile", "knowledge_observation"],
      apiRules: [
        {
          name: "douyin-web-api",
          host: "www.douyin.com",
          pathPrefixes: ["/aweme/v1/web/", "/api/"]
        }
      ]
    },
    {
      id: "xqttool",
      pageHosts: ["xqttool.com", "www.xqttool.com"],
      recordKinds: ["creator_profile", "knowledge_observation"],
      apiRules: [
        {
          name: "xqttool-api",
          host: "xqttool.com",
          pathPrefixes: ["/api/"]
        },
        {
          name: "xqttool-www-api",
          host: "www.xqttool.com",
          pathPrefixes: ["/api/"]
        }
      ]
    },
    {
      id: "oceanengine",
      pageHosts: ["cc.oceanengine.com", "www.oceanengine.com"],
      recordKinds: ["campaign_metrics"],
      apiRules: [
        {
          name: "oceanengine-api",
          host: "cc.oceanengine.com",
          pathPrefixes: ["/api/", "/open_api/"]
        }
      ]
    },
    {
      id: "xiaohongshu",
      pageHosts: ["xiaohongshu.com", "www.xiaohongshu.com"],
      recordKinds: ["unmapped_capture"],
      apiRules: []
    },
    {
      id: "taobao",
      pageHosts: ["www.taobao.com", "item.taobao.com"],
      recordKinds: ["unmapped_capture"],
      apiRules: []
    },
    {
      id: "tmall",
      pageHosts: ["www.tmall.com", "detail.tmall.com"],
      recordKinds: ["unmapped_capture"],
      apiRules: []
    },
    {
      id: "jd",
      pageHosts: ["www.jd.com", "item.jd.com"],
      recordKinds: ["unmapped_capture"],
      apiRules: []
    }
  ];

  function parseUrl(rawUrl) {
    try {
      return new URL(String(rawUrl || ""));
    } catch (_error) {
      return null;
    }
  }

  function findPlatformByPageHost(hostname) {
    return SUPPORTED_PLATFORMS.find((platform) => platform.pageHosts.includes(String(hostname || "").toLowerCase())) || null;
  }

  function isReadOnlyCaptureMethod(method) {
    return READONLY_CAPTURE_METHODS.has(String(method || "").toUpperCase());
  }

  function isBlockedUrl(rawUrl) {
    const parsedUrl = rawUrl instanceof URL ? rawUrl : parseUrl(rawUrl);
    if (!parsedUrl) {
      return true;
    }
    const pathTokens = parsedUrl.pathname.toLowerCase().split(/[\\/._-]+/).filter(Boolean);
    if (pathTokens.some((token) => BLOCKED_PATH_FRAGMENTS.has(token) || [...PREFIX_BLOCKED_PATH_TOKENS].some((blocked) => token.startsWith(blocked)))) {
      return true;
    }
    return [...parsedUrl.searchParams.keys()].some((key) => SENSITIVE_QUERY_KEY_PATTERN.test(key));
  }

  function isPageCaptureAllowed(rawUrl) {
    const parsedUrl = rawUrl instanceof URL ? rawUrl : parseUrl(rawUrl);
    if (!parsedUrl || isBlockedUrl(parsedUrl)) {
      return false;
    }
    return parsedUrl.protocol === "https:" || (parsedUrl.protocol === "http:" && LOCAL_DEV_HOSTS.has(parsedUrl.hostname));
  }

  function matchesApiRule(platform, api) {
    if (!platform || !api || !isReadOnlyCaptureMethod(api.method)) {
      return false;
    }

    const parsedUrl = parseUrl(api.url);
    if (!parsedUrl || isBlockedUrl(parsedUrl)) {
      return false;
    }

    return platform.apiRules.some((rule) =>
      rule.name === api.matched_rule &&
      rule.host === parsedUrl.hostname &&
      rule.pathPrefixes.some((prefix) => parsedUrl.pathname.startsWith(prefix))
    );
  }

  function matchesGenericApiRule(pageUrl, api) {
    if (!api || !isReadOnlyCaptureMethod(api.method)) {
      return false;
    }
    const parsedPageUrl = parseUrl(pageUrl);
    const parsedApiUrl = parseUrl(api.url);
    if (!parsedPageUrl || !parsedApiUrl || !isPageCaptureAllowed(parsedPageUrl) || isBlockedUrl(parsedApiUrl)) {
      return false;
    }
    return parsedPageUrl.origin === parsedApiUrl.origin;
  }

  globalThis.AgentXConnectorPlatformPolicy = Object.freeze({
    supportedPlatforms: SUPPORTED_PLATFORMS,
    blockedPathFragments: [...BLOCKED_PATH_FRAGMENTS],
    findPlatformByPageHost,
    isReadOnlyCaptureMethod,
    isBlockedUrl,
    isPageCaptureAllowed,
    matchesApiRule,
    matchesGenericApiRule
  });
})();
