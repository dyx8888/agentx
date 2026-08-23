import json
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKGROUND_PATH = PROJECT_ROOT / "browser-extension" / "agentx-connector" / "src" / "background.js"
INJECTED_PATH = PROJECT_ROOT / "browser-extension" / "agentx-connector" / "src" / "injected.js"
E2E_PATH = PROJECT_ROOT / "frontend" / "e2e" / "browser-connector-extension.spec.js"


def _run_background_policy_probe(host_permissions, endpoints):
    script = f"""
const fs = require("fs");
const vm = require("vm");
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
vm.runInNewContext(source, context, {{ filename: "background.js" }});
const helper = context.__AGENTX_CONNECTOR_TEST__;
const result = {{
  endpoints: Object.fromEntries(Object.entries(endpoints).map(([name, value]) => [name, helper.validateEndpoint(value)])),
  methods: {{
    GET: helper.isReadOnlyCaptureMethod("GET"),
    HEAD: helper.isReadOnlyCaptureMethod("HEAD"),
    POST: helper.isReadOnlyCaptureMethod("POST"),
    PUT: helper.isReadOnlyCaptureMethod("PUT"),
    PATCH: helper.isReadOnlyCaptureMethod("PATCH"),
    DELETE: helper.isReadOnlyCaptureMethod("DELETE")
  }}
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


def test_background_endpoint_policy_accepts_only_manifest_granted_ingest_urls():
    result = _run_background_policy_probe(
        ["http://localhost/*", "http://127.0.0.1/*", "https://api.example.com/*"],
        {
            "localhost": "http://localhost:8000/api/browser-connector/ingest",
            "loopback": "http://127.0.0.1:8000/api/browser-connector/ingest",
            "https": "https://api.example.com/api/browser-connector/ingest",
            "http_remote": "http://api.example.com/api/browser-connector/ingest",
            "query": "https://api.example.com/api/browser-connector/ingest?token=secret",
            "fragment": "https://api.example.com/api/browser-connector/ingest#secret",
            "userinfo": "https://user:pass@api.example.com/api/browser-connector/ingest",
            "wrong_path": "https://api.example.com/api/not-connector",
            "ungranted_origin": "https://other.example.com/api/browser-connector/ingest",
        },
    )

    assert result["endpoints"]["localhost"]["ok"] is True
    assert result["endpoints"]["loopback"]["ok"] is True
    assert result["endpoints"]["https"]["ok"] is True
    for name in ("http_remote", "query", "fragment", "userinfo", "wrong_path", "ungranted_origin"):
        assert result["endpoints"][name]["ok"] is False


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


def test_extension_sources_keep_get_only_capture_and_sensitive_payload_guardrails():
    injected = INJECTED_PATH.read_text(encoding="utf-8")
    background = BACKGROUND_PATH.read_text(encoding="utf-8")
    e2e = E2E_PATH.read_text(encoding="utf-8")

    assert 'new Set(["GET", "HEAD"])' in injected
    assert "isReadOnlyCaptureMethod(requestInfo.method)" in injected
    assert "isReadOnlyCaptureMethod(meta.method)" in injected
    assert 'reason: "invalid_endpoint"' in background
    assert "endpointCheck.endpoint" in background
    assert "endpoint," not in background.split('reason: "invalid_endpoint"', 1)[1].split("});", 1)[0]
    assert "expect(postCapture).toBeUndefined()" in e2e
    assert "expect(serialized).not.toContain('request-body-should-not-be-collected')" in e2e
    assert "expect(serialized).not.toContain('post-authorization-should-not-be-collected')" in e2e
    assert "expect(serialized).not.toContain('platform-cookie-should-not-be-collected')" in e2e
