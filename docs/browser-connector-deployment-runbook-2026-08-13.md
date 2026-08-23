# Browser Connector Deployment Validation Runbook - 2026-08-13

This runbook is for the isolated `codex/browser-connector-mvp` branch only. It validates whether a staging or production-like AgentX deployment can receive sanitized browser-extension captures through the authenticated connector path.

Do not paste real secrets, production cookies, platform tokens, or captured raw platform payloads into this file.

## 1. Deployment Inputs

Record these values before testing:

- Frontend origin: `https://<agentx-frontend-host>`
- Backend origin: `https://<agentx-backend-host>`
- Ingest endpoint: `https://<agentx-backend-host>/api/browser-connector/ingest`
- Test tenant/company id:
- Test user:
- Extension commit:
- Extension id:
- Browser version:

## 2. Backend Environment

Required for connector staging validation:

```text
ENVIRONMENT=production
ENV=prod
FRONTEND_URL=https://<agentx-frontend-host>
CORS_ORIGINS=https://<agentx-frontend-host>
COOKIE_SECURE=true
COOKIE_SAMESITE=none
ENABLE_PUBLIC_DOCS=false
FEATURE_BROWSER_CONNECTOR_TENANT_IDS=<test-company-id>
```

Rationale:

- `COOKIE_SECURE=true` ensures AgentX auth cookies are sent only over HTTPS.
- `COOKIE_SAMESITE=none` is required for browser-extension background requests that post to the AgentX backend from an extension origin.
- `CORS_ORIGINS` must list exact AgentX web origins only; do not use `*` in production-like environments.
- `FEATURE_BROWSER_CONNECTOR_TENANT_IDS` should list only the staging or pilot company ids under validation.
- `FEATURE_BROWSER_CONNECTOR=true` is a global rollout switch and should stay unset for limited pilots.

If the deployment is not validating the browser connector, keep the default `COOKIE_SAMESITE=lax` posture for normal web sessions.

## 3. Extension Manifest

The local MVP manifest only grants local backend transport:

```text
http://localhost/*
http://127.0.0.1/*
```

For staging validation:

1. Create a disposable packaging directory outside the committed extension source.
2. Copy the extension files into that disposable directory.
3. Generate the deployment manifest with the exact backend origin:

```powershell
python browser-extension/agentx-connector/tools/build_deployment_manifest.py `
  --backend "https://<agentx-backend-host>" `
  --out "path\to\packaged-extension\manifest.json"
```

4. Confirm `host_permissions` contains only `https://<agentx-backend-host>/*`.
5. Do not add wildcard transport permissions such as `https://*/*`.
6. Keep platform page matches limited to the existing allowlisted platform hosts.
7. Load the disposable unpacked extension in Chrome or Edge.

Do not commit a manifest containing private or temporary staging domains unless the domain is intended to be reviewed with the branch.

## 4. API Preflight Checks

Run these checks against the deployed backend:

```powershell
$backend = "https://<agentx-backend-host>"
$frontend = "https://<agentx-frontend-host>"

Invoke-WebRequest `
  -Method Options `
  -Uri "$backend/api/browser-connector/ingest" `
  -Headers @{
    Origin = $frontend
    "Access-Control-Request-Method" = "POST"
    "Access-Control-Request-Headers" = "content-type,x-agentx-connector-version"
  }
```

Expected:

- HTTP 200 or 204.
- `access-control-allow-origin` equals the exact frontend origin.
- `access-control-allow-credentials` is `true`.
- The response does not reflect unconfigured origins.

Negative origin check:

```powershell
Invoke-WebRequest `
  -Method Options `
  -Uri "$backend/api/browser-connector/ingest" `
  -Headers @{
    Origin = "https://evil.example.com"
    "Access-Control-Request-Method" = "POST"
    "Access-Control-Request-Headers" = "content-type"
  }
```

Expected:

- The response does not set `access-control-allow-origin` to `https://evil.example.com`.

You can run the secret-safe staging probe to cover the same unauthenticated HTTP/CORS and
manifest-permission checks without pasting cookies or credentials:

```powershell
python tests/performance/browser_connector_staging_probe.py `
  --frontend "https://<agentx-frontend-host>" `
  --backend "https://<agentx-backend-host>" `
  --manifest "path\to\packaged-extension\manifest.json"
```

Expected:

- Frontend and backend URLs are HTTPS.
- Configured frontend origin can credential POST to `/api/browser-connector/ingest`.
- Unknown origins are not reflected by CORS.
- `/api/browser-connector/status` and `/api/browser-connector/ingest` reject unauthenticated requests.
- Packaged manifest includes only the exact backend origin permission and platform content-script matches.

## 5. Cookie Auth Checks

1. Open the AgentX frontend over HTTPS.
2. Log in as the test user.
3. In DevTools Application > Cookies, confirm:
   - `access_token` exists.
   - `HttpOnly` is enabled.
   - `Secure` is enabled.
   - `SameSite=None` is present for connector validation deployments.
4. Do not copy cookie values into notes, logs, screenshots, or test fixtures.

Expected API behavior:

- `POST /api/browser-connector/ingest` without login returns 401.
- `POST /api/browser-connector/ingest` from a non-pilot tenant returns `403 browser_connector_disabled`.
- `POST /api/browser-connector/ingest` after login succeeds through the browser-managed cookie.
- Client-provided `tenant_id`, `company_id`, and `user_id` are ignored.
- Stored events bind to the authenticated backend user.

## 6. Real Extension Capture Check

1. Configure the extension popup endpoint to:

```text
https://<agentx-backend-host>/api/browser-connector/ingest
```

2. Open an allowlisted platform page while logged into that platform.
3. Trigger a read-only page view that loads creator, campaign, or rule/knowledge data.
4. Confirm the extension delivery log records a successful POST.
5. Confirm AgentX Settings shows updated connector source counts.
6. Confirm the database has a new `browser_connector_events` row for the test tenant.

Sensitive data inspection:

- Search the stored JSON for `cookie`, `authorization`, `token`, `password`, `captcha`, `payment`, `card`, `secret`, `credential`, and `session`.
- The check must return no raw sensitive values.
- Redacted placeholders are acceptable only for response fields that were intentionally captured after allowlist matching.

Secret-safe database audit:

```powershell
python tests/performance/browser_connector_db_audit.py `
  --company-id "<test-company-id>" `
  --out "tests/reports/browser_connector_db_audit.json"
```

If the staging database is not available through the current `DATABASE_URL`, pass it as
`--database-url` from the deployment shell. Do not paste database URLs, passwords, cookies,
or raw platform payloads into notes or committed files.

Expected:

- The report shows at least one `browser_connector_events` row for the test company.
- `api_url_hash` and `payload_hash` are 64-character sha256 hex values.
- Stored connector metadata does not contain raw API URLs or query strings.
- Stored payload JSON does not contain cookie, Authorization, token, password, captcha,
  payment, card, secret, credential, or session markers.
- Normalization produces auditable record kinds such as `creator_profile`,
  `knowledge_observation`, `campaign_metrics`, or `unmapped_capture`.

## 7. Stop Conditions

Stop validation and do not expose the connector to users if any condition appears:

- `COOKIE_SAMESITE=none` is set without `COOKIE_SECURE=true`.
- CORS reflects arbitrary origins.
- `CORS_ORIGINS=*` is accepted in production-like mode.
- The extension manifest uses broad backend host permissions such as `https://*/*`.
- Ingest succeeds without a logged-in AgentX user.
- Ingest succeeds for a tenant not listed in `FEATURE_BROWSER_CONNECTOR_TENANT_IDS` while the global flag is off.
- Ingest trusts client-provided tenant or user identity.
- Stored payloads contain raw cookie, Authorization, token, password, captcha, payment, or request-body values.
- The connector triggers any platform write operation.

## 8. Local Regression Commands

Run before considering a staging validation result current:

```powershell
python -m pytest tests/api/test_browser_connector_cors_auth.py -q
```

```powershell
python -m pytest tests/performance/test_browser_connector_staging_probe.py -q
```

```powershell
python -m pytest tests/performance/test_browser_connector_manifest_builder.py -q
```

```powershell
python -m pytest tests/performance/test_browser_connector_db_audit.py -q
```

```powershell
python -m pytest tests/performance/test_browser_connector_live_evidence_template.py tests/performance/test_browser_connector_pilot_readiness_audit.py -q
```

```powershell
cd frontend
npm.cmd exec -- playwright test --config=playwright.browser-connector.config.js
```

If these local gates fail, fix them before running or trusting staging validation.

You can use the evidence bundle runner to execute the manifest, staging probe,
DB audit, live evidence template, and readiness audit commands in a fixed order:

```powershell
python tests/performance/browser_connector_evidence_bundle.py `
  --frontend "https://<agentx-frontend-host>" `
  --backend "https://<agentx-backend-host>" `
  --company-id "<test-company-id>" `
  --expected-extension-commit "<git-short-sha>"
```

Before real staging credentials are available, use `--dry-run` to review the
planned command sequence without opening network or database connections. A
dry-run report is not real pilot evidence.

After staging probe, DB audit, and manual live evidence are collected, run the
readiness boundary audit. Evidence is valid for 72 hours by default; rerun the
staging probe, DB audit, and manual browser check when evidence is older:

```powershell
python tests/performance/browser_connector_pilot_readiness_audit.py `
  --staging-probe "tests/reports/browser_connector_staging_probe.json" `
  --db-audit "tests/reports/browser_connector_db_audit.json" `
  --manual-evidence "tests/reports/browser_connector_live_evidence.json" `
  --max-evidence-age-hours 72 `
  --require-pilot-ready
```

## 9. Evidence Template

Record only non-secret evidence:

Generate the JSON template first:

```powershell
python tests/performance/browser_connector_live_evidence_template.py `
  --out "tests/reports/browser_connector_live_evidence.json"
```

```text
generated_at:
Backend origin:
Frontend origin:
Extension commit:
Extension id:
Browser:
Test user:
Test company_id:
Feature flag / allowlist setting:
CORS preflight allowed origin result:
CORS negative origin result:
Cookie flags observed:
Ingest unauthenticated result:
Ingest authenticated result:
Stored event id:
Normalized record kinds:
DB audit report:
Settings source counts:
Sensitive value scan result:
Platform write operation observed:
Pilot readiness audit:
Tester:
```

The connector is not ready for real-user pilot use until this evidence is complete,
the local regression commands pass, and `browser_connector_pilot_readiness_audit.py
--require-pilot-ready` returns success.
