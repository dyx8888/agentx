# Public Security Review - 2026-08-11

This document records the current public-demo security review for AgentX. It is based on local repository inspection and does not replace a hosted penetration test or production cloud review.

## Verified Locally

- Display branch is clean.
- Tracked runtime artifact count is `0`.
- High-confidence secret scan has `0` hits.
- Sensitive config placeholders are blank, env-interpolated, or obvious placeholders; filled sensitive config value count is `0`.
- `backend/data/**`, `reports/**`, `tests/reports/**`, `frontend/screenshots/**`, and `perf_*` are not tracked.
- Production mode rejects wildcard CORS origins.
- Production docs and OpenAPI paths are disabled when `ENABLE_PUBLIC_DOCS=false`.
- Evolution / LoRA API routes and background services are disabled by default when `ENABLE_EVOLUTION_API=false`.
- `COOKIE_SECURE=true` is required in the production environment template.
- `JWT_SECRET_KEY` is required through environment configuration.
- Backend and frontend environment templates contain placeholders only.
- Known weak local Docker/Postgres defaults were removed from tracked config text.
- `tests/performance/public_demo_security_audit.py` provides a repeatable local
  repository security audit before push/deploy.

## Broad Scan Notes

A loose keyword scan still finds fake keys in tests, examples, and docs, for example:

- `sk-abc123`
- `sk-test`
- `sk-live`
- `sk-xxxxxxxxxxxxxxxx`

These are non-secret fixtures or placeholders. They should remain clearly fake and must not be replaced with real keys.

## Admin Route Boundary

`backend/app/api/admin/admin.py` contains development mock admin/company/user/usage fallback helpers, but production mode now disables those fallbacks.

Verified behavior:

- In `ENVIRONMENT=production` / `ENV=prod`, empty or unavailable admin data sources return empty admin lists instead of mock admin/company/user/usage data.
- Outside production, development mock fallbacks remain available for local UI development.
- `backend/tests/test_admin_production_mock_policy.py` covers the production-disabled and development-allowed paths.

Current decision:

- This does not expand the minimum public demo surface; admin pages remain outside the public portfolio demo.
- Admin routes still require an authenticated admin user.
- Do not expose an admin UI publicly until real database-backed admin data and smoke coverage are reviewed.

## External Integration Boundary

External integrations remain unverified:

- OAuth providers
- SMTP delivery
- Taobao / Douyin / Pinduoduo / Xiaohongshu platform APIs
- Milvus-backed RAG quality

Required behavior before public completion:

- Missing credentials must show `not connected` or `configuration required`.
- Missing platform credentials must not produce fake execution success.
- High-risk actions must create drafts or human-review states only.

## Public Exposure Rules

Before a public URL is shared:

- Set exact `CORS_ORIGINS`.
- Set `FRONTEND_URL`.
- Set `COOKIE_SECURE=true`.
- Set `ENABLE_PUBLIC_DOCS=false`.
- Set `ENABLE_EVOLUTION_API=false`.
- Generate `JWT_SECRET_KEY` in the hosting platform.
- Do not upload local DB files.
- Do not enable Swagger/OpenAPI publicly unless it is a private review deployment.
- Do not include real platform tokens, OAuth secrets, SMTP passwords, or cookies in repo files, logs, reports, screenshots, or recordings.

## Still Required

Security is not complete until:

- Public frontend and backend URLs exist.
- HTTPS is verified.
- Public smoke confirms auth, CORS, cookies, and degraded external integrations.
- Managed Postgres migration is verified without local data import.
- Public smoke results are recorded in `docs/public-demo-smoke-template-2026-08-11.md` or a completed successor document.
