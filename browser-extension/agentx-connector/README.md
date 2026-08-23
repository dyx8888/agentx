# AgentX Browser Connector MVP

Phase 1 scope: a Chrome Manifest V3 extension that passively captures allowlisted API responses from approved ecommerce/creator-marketing pages and forwards sanitized structured payloads to AgentX.

## What this MVP does

- Injects a page script from a content script.
- Hooks `window.fetch` and `XMLHttpRequest`.
- Captures only API responses matching the allowlist in `src/injected.js`.
- Sends sanitized structured data to the configured AgentX endpoint.
- Keeps a small local delivery log for debugging.

## What this MVP does not do

- Does not modify Chat, KOL, Knowledge, Settings, or backend code.
- Does not perform platform write actions.
- Does not read or forward cookies.
- Does not read or forward request headers, including `Authorization`.
- Does not read or forward request bodies.
- Redacts sensitive response fields such as password, token, captcha, payment, card, secret, credential, and session fields.

## Local install

1. Open `chrome://extensions`.
2. Enable Developer mode.
3. Click `Load unpacked`.
4. Select this directory: `browser-extension/agentx-connector`.
5. Open the popup and confirm the AgentX ingest URL.

Default endpoint:

```text
http://localhost:8000/api/browser-connector/ingest
```

The backend endpoint must return `202 Accepted` for a successful delivery. If it is offline,
the extension keeps a local failed-delivery entry without changing platform page behavior.

## Deployment manifest

Do not edit the committed local `manifest.json` with private staging domains. Build a disposable
deployment manifest for the packaged extension:

```text
python browser-extension/agentx-connector/tools/build_deployment_manifest.py ^
  --backend https://api-staging.example.com ^
  --out C:\temp\agentx-connector-package\manifest.json
```

The helper writes exactly one backend `host_permissions` entry, for example
`https://api-staging.example.com/*`, preserves the platform content-script matches, and rejects
broad permissions such as `https://*/*`.

## Real browser E2E

Run the focused Playwright check from the frontend workspace:

```text
cd frontend
npm.cmd exec -- playwright test --config=playwright.browser-connector.config.js
```

The test launches a persistent Chromium-compatible browser with this unpacked MV3 extension,
loads a routed `buyin.jinritemai.com` fixture page, exercises both `fetch` and
`XMLHttpRequest`, and verifies that:

- allowlisted API responses are delivered to a local ingest endpoint;
- non-allowlisted API responses are ignored;
- request headers, cookies, request bodies, and URL secrets are not forwarded;
- sensitive response fields are redacted before delivery.

Set `PLAYWRIGHT_EXTENSION_CHANNEL=chrome` if Edge is unavailable and Chrome is installed.

## Allowlist

The first-phase allowlist is intentionally narrow and lives in `src/injected.js`.

Default hosts:

- `buyin.jinritemai.com`
- `compass.jinritemai.com`
- `fxg.jinritemai.com`
- `www.douyin.com`
- `xqttool.com`
- `www.xqttool.com`
- `cc.oceanengine.com`

Default path matching captures JSON-like API endpoints only. Expand this list explicitly during future connector work rather than broadening to all traffic.

## Security boundary

This connector is read-only. It collects response data after an allowlist match, sanitizes it in the page context, forwards it through the extension background worker, and posts it to AgentX with browser-managed credentials only. It never inspects cookie values or platform auth headers.
