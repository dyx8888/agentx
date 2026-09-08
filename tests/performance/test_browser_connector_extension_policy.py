import json
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKGROUND_PATH = PROJECT_ROOT / "browser-extension" / "agentx-connector" / "src" / "background.js"
POPUP_PATH = PROJECT_ROOT / "browser-extension" / "agentx-connector" / "src" / "popup.js"
CONTENT_SCRIPT_PATH = PROJECT_ROOT / "browser-extension" / "agentx-connector" / "src" / "content-script.js"
INJECTED_PATH = PROJECT_ROOT / "browser-extension" / "agentx-connector" / "src" / "injected.js"
PLATFORM_POLICY_PATH = PROJECT_ROOT / "browser-extension" / "agentx-connector" / "src" / "platform-policy.js"
E2E_PATH = PROJECT_ROOT / "frontend" / "e2e" / "browser-connector-extension.spec.js"
MANIFEST_PATH = PROJECT_ROOT / "browser-extension" / "agentx-connector" / "manifest.json"


def _load_platform_policy():
    script = f"""
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync({json.dumps(str(PLATFORM_POLICY_PATH))}, "utf8");
const context = {{ URL, Set, Object, globalThis: null }};
context.globalThis = context;
vm.runInNewContext(source, context, {{ filename: "platform-policy.js" }});
process.stdout.write(JSON.stringify(context.AgentXConnectorPlatformPolicy.supportedPlatforms));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )
    return json.loads(completed.stdout)


def _run_background_policy_probe(host_permissions, endpoints):
    script = f"""
const fs = require("fs");
const vm = require("vm");
const policySource = fs.readFileSync({json.dumps(str(PLATFORM_POLICY_PATH))}, "utf8");
const source = fs.readFileSync({json.dumps(str(BACKGROUND_PATH))}, "utf8");
const endpoints = {json.dumps(endpoints)};
const context = {{
  URL,
  Set,
  String,
  Number,
  Date,
  JSON,
  globalThis: null,
  importScripts: () => undefined,
  __AGENTX_CONNECTOR_TEST_ENABLE__: true,
  chrome: {{
    runtime: {{
      id: "test-extension",
      getManifest: () => ({{ host_permissions: {json.dumps(host_permissions)} }}),
      onInstalled: {{ addListener: () => undefined }},
      onMessage: {{ addListener: () => undefined }}
    }},
    storage: {{ local: {{ get: async () => ({{}}), set: async () => undefined }} }}
  }}
}};
context.globalThis = context;
vm.runInNewContext(policySource, context, {{ filename: "platform-policy.js" }});
vm.runInNewContext(source, context, {{ filename: "background.js" }});
const helper = context.__AGENTX_CONNECTOR_TEST__;
const captureCases = {{
  valid: {{
    api: {{
      url: "https://buyin.jinritemai.com/square_pc_api/square/search_feed_author",
      method: "GET",
      matched_rule: "buyin-api"
    }},
    data: {{ kind: "json", value: {{ nickname: "Safe Creator", follower_count: 12 }} }}
  }},
  wrongApiHost: {{
    api: {{
      url: "https://example.invalid/api/creator",
      method: "GET",
      matched_rule: "buyin-api"
    }},
    data: {{ kind: "json", value: {{ nickname: "Safe Creator" }} }}
  }},
  writeMethod: {{
    api: {{
      url: "https://buyin.jinritemai.com/square_pc_api/square/search_feed_author",
      method: "POST",
      matched_rule: "buyin-api"
    }},
    data: {{ kind: "json", value: {{ nickname: "Safe Creator" }} }}
  }},
  sensitive: {{
    api: {{
      url: "https://buyin.jinritemai.com/square_pc_api/square/search_feed_author",
      method: "GET",
      matched_rule: "buyin-api"
    }},
    data: {{ kind: "json", value: {{ nickname: "Safe Creator", token: "must-not-pass" }} }}
  }},
  xiaohongshuUnverified: {{
    api: {{
      url: "https://edith.xiaohongshu.com/api/sns/web/v1/feed",
      method: "GET",
      matched_rule: "xiaohongshu-public-api"
    }},
    data: {{ kind: "json", value: {{ nickname: "Safe Creator" }} }}
  }},
  blockedPath: {{
    api: {{
      url: "https://buyin.jinritemai.com/mpa/api/pigeon/messages",
      method: "GET",
      matched_rule: "buyin-api"
    }},
    data: {{ kind: "json", value: {{ nickname: "Safe Creator" }} }}
  }}
}};
const senders = {{
  buyin: {{ tab: {{ url: "https://buyin.jinritemai.com/dashboard" }} }},
  xiaohongshu: {{ tab: {{ url: "https://www.xiaohongshu.com/explore" }} }}
}};
  const result = {{
    endpoints: Object.fromEntries(Object.entries(endpoints).map(([name, value]) => [name, helper.validateEndpoint(value)])),
    normalized: Object.fromEntries(Object.entries(endpoints).map(([name, value]) => {{
      const check = helper.validateEndpoint(value);
      return [name, check.ok ? check.endpoint : null];
    }})),
    methods: {{
      GET: helper.isReadOnlyCaptureMethod("GET"),
    HEAD: helper.isReadOnlyCaptureMethod("HEAD"),
    POST: helper.isReadOnlyCaptureMethod("POST"),
    PUT: helper.isReadOnlyCaptureMethod("PUT"),
    PATCH: helper.isReadOnlyCaptureMethod("PATCH"),
    DELETE: helper.isReadOnlyCaptureMethod("DELETE")
  }},
  captures: {{
    valid: helper.isAllowedCapture(captureCases.valid, senders.buyin),
    wrongPage: helper.isAllowedCapture(captureCases.valid, senders.xiaohongshu),
    wrongApiHost: helper.isAllowedCapture(captureCases.wrongApiHost, senders.buyin),
    writeMethod: helper.isAllowedCapture(captureCases.writeMethod, senders.buyin),
    sensitive: helper.isAllowedCapture(captureCases.sensitive, senders.buyin),
    xiaohongshuUnverified: helper.isAllowedCapture(captureCases.xiaohongshuUnverified, senders.xiaohongshu),
    blockedPath: helper.isAllowedCapture(captureCases.blockedPath, senders.buyin)
  }},
  sanitized: helper.normalizeStructuredData({{
    token: "must-not-store",
    email: "private@example.test",
    note: "safe note",
    nested: {{ phone: "13800138000", visible: "safe visible value" }}
  }})
}};
process.stdout.write(JSON.stringify(result));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )
    return json.loads(completed.stdout)


def _run_content_script_probe(hostname):
    script = f"""
const fs = require("fs");
const vm = require("vm");
const policySource = fs.readFileSync({json.dumps(str(PLATFORM_POLICY_PATH))}, "utf8");
const source = fs.readFileSync({json.dumps(str(CONTENT_SCRIPT_PATH))}, "utf8");
const localStorage = new Map();
const appendedScripts = [];
const dispatchedEvents = [];
const attributes = new Map();
const context = {{
  Set,
  URL,
  Event: function Event(type) {{ this.type = type; }},
  window: null,
  document: {{
    createElement: (tagName) => ({{ tagName, remove: () => undefined }}),
    documentElement: {{
      appendChild: (script) => appendedScripts.push(script),
      setAttribute: (key, value) => attributes.set(key, value),
      removeAttribute: (key) => attributes.delete(key)
    }},
    head: null,
    body: {{ innerText: "" }},
    querySelectorAll: () => []
  }},
  chrome: {{
    runtime: {{
      getURL: (path) => `chrome-extension://test-extension/${{path}}`,
      onMessage: {{ addListener: () => undefined }},
      sendMessage: async () => ({{ ok: true }})
    }}
  }}
}};
context.window = {{
  __AGENTX_CONNECTOR_CONTENT_SCRIPT__: false,
  location: {{
    hostname: {json.dumps(hostname)},
    href: {json.dumps(f"https://{hostname}/public/page")},
    origin: {json.dumps(f"https://{hostname}")}
  }},
  localStorage: {{
    setItem: (key, value) => localStorage.set(key, value)
  }},
  dispatchEvent: (event) => dispatchedEvents.push(event.type),
  addEventListener: () => undefined
}};
vm.runInNewContext(policySource, context, {{ filename: "platform-policy.js" }});
vm.runInNewContext(source, context, {{ filename: "content-script.js" }});
process.stdout.write(JSON.stringify({{
  status: localStorage.get("agentx_browser_connector_status") || null,
  events: dispatchedEvents,
  injectedScriptCount: appendedScripts.length,
  injectedScriptSrc: appendedScripts[0] && appendedScripts[0].src ? appendedScripts[0].src : null,
  capturePolicy: attributes.get("data-agentx-connector-capture-policy") || null
}}));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )
    return json.loads(completed.stdout)


def _run_popup_probe(host_permissions, stored_endpoint, typed_endpoint):
    script = f"""
const fs = require("fs");
const vm = require("vm");
const source = fs.readFileSync({json.dumps(str(POPUP_PATH))}, "utf8");
const elements = {{
  enabled: {{ checked: true }},
  endpoint: {{ value: "", title: "" }},
  save: {{ addEventListener: () => undefined }},
  captureCurrentPage: {{ addEventListener: () => undefined }},
  statusBadge: {{ textContent: "", classList: {{ toggle: () => undefined }} }},
  queuedCount: {{ textContent: "" }},
  lastStatus: {{ textContent: "" }}
}};
const storage = {{ settings: {{ enabled: true, endpoint: {json.dumps(stored_endpoint)} }} }};
const context = {{
  URL,
  Set,
  String,
  Boolean,
  globalThis: null,
  __AGENTX_CONNECTOR_TEST_ENABLE__: true,
  document: {{
    addEventListener: () => undefined,
    getElementById: (id) => elements[id]
  }},
  chrome: {{
    runtime: {{
      getManifest: () => ({{ host_permissions: {json.dumps(host_permissions)} }}),
      sendMessage: async () => ({{ ok: false }})
    }},
    tabs: {{ query: async () => [] }},
    storage: {{
      local: {{
        get: async () => storage,
        set: async (value) => Object.assign(storage, value)
      }}
    }}
  }}
}};
context.globalThis = context;
vm.runInNewContext(source, context, {{ filename: "popup.js" }});
const helper = context.__AGENTX_CONNECTOR_POPUP_TEST__;
(async () => {{
  await helper.loadState();
  const afterLoad = {{ value: elements.endpoint.value, title: elements.endpoint.title, storage: storage.settings.endpoint }};
  elements.endpoint.value = {json.dumps(typed_endpoint)};
  await helper.saveSettings();
  const afterSave = {{ value: elements.endpoint.value, title: elements.endpoint.title, storage: storage.settings.endpoint, status: elements.lastStatus.textContent }};
  process.stdout.write(JSON.stringify({{ afterLoad, afterSave }}));
}})().catch((error) => {{
  console.error(error && error.stack ? error.stack : error);
  process.exit(1);
}});
"""
    completed = subprocess.run(
        ["node", "-e", script],
        check=True,
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )
    return json.loads(completed.stdout)


def test_background_endpoint_policy_accepts_only_manifest_granted_ingest_urls():
    result = _run_background_policy_probe(
        ["http://localhost/*", "http://127.0.0.1/*", "https://api.example.com/*"],
        {
            "localhost": "http://localhost:8000/api/browser-connector/ingest",
            "localhost_origin": "http://localhost:8000",
            "loopback": "http://127.0.0.1:8000/api/browser-connector/ingest",
            "https": "https://api.example.com/api/browser-connector/ingest",
            "https_origin": "https://api.example.com",
            "http_remote": "http://api.example.com/api/browser-connector/ingest",
            "query": "https://api.example.com/api/browser-connector/ingest?token=secret",
            "fragment": "https://api.example.com/api/browser-connector/ingest#secret",
            "userinfo": "https://user:pass@api.example.com/api/browser-connector/ingest",
            "wrong_path": "https://api.example.com/api/not-connector",
            "ungranted_origin": "https://other.example.com/api/browser-connector/ingest",
        },
    )

    assert result["endpoints"]["localhost"]["ok"] is True
    assert result["endpoints"]["localhost_origin"]["ok"] is True
    assert result["normalized"]["localhost_origin"] == "http://localhost:8000/api/browser-connector/ingest"
    assert result["endpoints"]["loopback"]["ok"] is True
    assert result["endpoints"]["https"]["ok"] is True
    assert result["endpoints"]["https_origin"]["ok"] is True
    assert result["normalized"]["https_origin"] == "https://api.example.com/api/browser-connector/ingest"
    for name in ("http_remote", "query", "fragment", "userinfo", "wrong_path", "ungranted_origin"):
        assert result["endpoints"][name]["ok"] is False


def test_popup_migrates_origin_only_endpoint_and_saves_canonical_ingest_url():
    result = _run_popup_probe(
        ["https://api.example.com/*"],
        stored_endpoint="https://api.example.com",
        typed_endpoint="https://api.example.com",
    )

    assert result["afterLoad"] == {
        "value": "https://api.example.com/api/browser-connector/ingest",
        "title": "https://api.example.com/api/browser-connector/ingest",
        "storage": "https://api.example.com/api/browser-connector/ingest",
    }
    assert result["afterSave"] == {
        "value": "https://api.example.com/api/browser-connector/ingest",
        "title": "https://api.example.com/api/browser-connector/ingest",
        "storage": "https://api.example.com/api/browser-connector/ingest",
        "status": "Saved",
    }


def test_content_script_reports_connector_status_on_agentx_app_without_capture_hook():
    result = _run_content_script_probe("agentx-fnbfc0d1r-dyx8888s-projects.vercel.app")

    assert result["status"] == "connected"
    assert result["events"] == ["agentx-browser-connector-status"]
    assert result["injectedScriptCount"] == 0
    assert result["injectedScriptSrc"] is None


def test_content_script_keeps_capture_hook_on_allowlisted_platform_hosts():
    result = _run_content_script_probe("buyin.jinritemai.com")

    assert result["status"] is None
    assert result["events"] == []
    assert result["injectedScriptCount"] == 1
    assert result["injectedScriptSrc"] == "chrome-extension://test-extension/src/injected.js"
    assert result["capturePolicy"] is not None


def test_content_script_injects_on_xiaohongshu_without_enabling_unverified_api_paths():
    result = _run_content_script_probe("www.xiaohongshu.com")

    assert result["injectedScriptCount"] == 1
    assert json.loads(result["capturePolicy"]) == {"id": "xiaohongshu", "apiRules": []}


def test_content_script_injects_idle_hook_on_a_generic_https_host():
    result = _run_content_script_probe("example.invalid")

    assert result["injectedScriptCount"] == 1
    assert json.loads(result["capturePolicy"]) == {"id": "generic", "apiRules": []}


def test_background_method_policy_is_get_head_only():
    result = _run_background_policy_probe(
        ["http://localhost/*"],
        {"localhost": "http://localhost:8000/api/browser-connector/ingest"},
    )

    assert result["methods"] == {
        "GET": True,
        "HEAD": True,
        "POST": False,
        "PUT": False,
        "PATCH": False,
        "DELETE": False,
    }


def test_background_rechecks_platform_origin_api_rule_and_sanitizes_payloads():
    result = _run_background_policy_probe(
        ["http://localhost/*"],
        {"localhost": "http://localhost:8000/api/browser-connector/ingest"},
    )

    assert result["captures"] == {
        "valid": True,
        "wrongPage": False,
        "wrongApiHost": False,
        "writeMethod": False,
        "sensitive": False,
        "xiaohongshuUnverified": False,
        "blockedPath": False,
    }
    assert result["sanitized"] == {
        "note": "safe note",
        "nested": {"visible": "safe visible value"},
    }


def test_manifest_supports_wide_https_injection_without_cookie_access():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    policy = _load_platform_policy()
    content_matches = set(manifest["content_scripts"][0]["matches"])
    resource_matches = set(manifest["web_accessible_resources"][0]["matches"])

    assert "https://*/*" in content_matches
    assert "https://*/*" in resource_matches
    assert "https://*/*" in manifest["host_permissions"]
    assert {"activeTab", "scripting", "storage", "tabs"} == set(manifest["permissions"])
    assert "cookies" not in manifest["permissions"]

    for platform in policy:
        for host in platform["pageHosts"]:
            assert host

    xiaohongshu = next(platform for platform in policy if platform["id"] == "xiaohongshu")
    assert xiaohongshu["apiRules"] == []


def test_extension_sources_keep_get_only_capture_and_sensitive_payload_guardrails():
    injected = INJECTED_PATH.read_text(encoding="utf-8")
    background = BACKGROUND_PATH.read_text(encoding="utf-8")
    e2e = E2E_PATH.read_text(encoding="utf-8")

    assert 'new Set(["GET", "HEAD"])' in injected
    assert "isReadOnlyCaptureMethod(requestInfo.method)" in injected
    assert "isReadOnlyCaptureMethod(meta.method)" in injected
    assert "const SUPPORTED_PLATFORMS" not in injected
    policy = PLATFORM_POLICY_PATH.read_text(encoding="utf-8")
    assert "AgentXConnectorPlatformPolicy" in CONTENT_SCRIPT_PATH.read_text(encoding="utf-8")
    assert 'id: "xiaohongshu"' in policy
    assert "generic-web-page" in CONTENT_SCRIPT_PATH.read_text(encoding="utf-8")
    assert "generic-api-capture" in INJECTED_PATH.read_text(encoding="utf-8")
    assert "GENERIC_CAPTURE_WINDOW_MS" in INJECTED_PATH.read_text(encoding="utf-8")
    assert "BLOCKED_PATH_FRAGMENTS" in policy
    assert 'importScripts("platform-policy.js")' in background
    assert "SENSITIVE_KEY_PATTERN" in CONTENT_SCRIPT_PATH.read_text(encoding="utf-8")
    assert "capture_not_allowlisted" in background
    assert "isAllowedCapture" in background
    assert "SENSITIVE_KEY_PATTERN" in background
    assert "chrome.scripting.executeScript" in background
    assert 'reason: "invalid_endpoint"' in background
    assert "endpointCheck.endpoint" in background
    assert "endpoint," not in background.split('reason: "invalid_endpoint"', 1)[1].split("});", 1)[0]
    assert "expect(postCapture).toBeUndefined()" in e2e
    assert "expect(serialized).not.toContain('request-body-should-not-be-collected')" in e2e
    assert "expect(serialized).not.toContain('post-authorization-should-not-be-collected')" in e2e
    assert "expect(serialized).not.toContain('platform-cookie-should-not-be-collected')" in e2e
