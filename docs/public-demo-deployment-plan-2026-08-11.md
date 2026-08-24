# Public Demo Deployment Plan - 2026-08-11

This document defines the recommended public-demo deployment path for AgentX. It is a planning artifact only; no cloud resources have been created from this document.

## Recommendation

Use a low-operations split deployment. The selected first-attempt provider path
is:

- Frontend: Vercel
- Backend: Render Web Service
- Database: Neon Postgres
- Redis / Milvus / SMTP / OAuth / platform APIs: optional, disabled or marked `not connected` until real credentials are configured

This path is preferred for the first public demo because the frontend is a Vite static build and the backend can be started as a FastAPI web service without requiring Docker full smoke first.

Render Static Site, Render Postgres, Supabase, Railway, Fly.io, or VPS remain
fallback options only if the selected path fails for a concrete provider limit.

## Frontend Deployment

Selected provider: Vercel.

Settings:

- Root directory: `frontend`
- Install command: `npm ci`
- Build command: `npm run build`
- Publish directory: `dist`
- Optional config file: `frontend/vercel.json`

Required environment variables:

- `VITE_API_BASE_URL=https://<backend-public-url>/api`

Optional environment variables:

- `VITE_WS_BASE=wss://<backend-public-url>/ws`
- `VITE_DEMO_ENABLED=false`
- `VITE_DEMO_USERNAME=`
- `VITE_DEMO_PASSWORD=`

Production demo login should remain disabled unless a controlled backend demo account is explicitly created.

## Backend Deployment

Selected provider: Render Web Service.

Settings:

- Root directory: repository root
- Build command: `python -m pip install -r backend/requirements.txt`
- Start command: `PYTHONPATH=backend uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Health check path: `/health`
- Example blueprint: `deploy/render.example.yaml`

Required environment variables:

- `ENVIRONMENT=production`
- `ENV=prod`
- `DATABASE_URL=<managed-postgres-url>`
- `JWT_SECRET_KEY=<generated-secret>`
- `FRONTEND_URL=https://<frontend-public-url>`
- `CORS_ORIGINS=https://<frontend-public-url>`
- `COOKIE_SECURE=true`
- `PUBLIC_REGISTRATION_ENABLED=false`
- `ENABLE_PUBLIC_DOCS=false`
- `ENABLE_EVOLUTION_API=false`

Optional environment variables:

- `REDIS_URL=`
- `MILVUS_HOST=`
- `MILVUS_PORT=19530`
- `SMTP_HOST=`
- `SMTP_PORT=587`
- `SMTP_USER=`
- `SMTP_PASSWORD=`
- `SMTP_FROM=`
- `SMTP_USE_TLS=true`
- `OAUTH_REDIRECT_BASE_URL=https://<backend-public-url>`
- Platform API keys and secrets for Taobao, Douyin, Pinduoduo, and Xiaohongshu
- Model provider API keys

If native build fails because of heavy model or vector dependencies, review a Docker-based backend deployment separately. Do not switch to Docker deployment without a separate Docker build and smoke review.

## Secret-Safe Preflight

Before sharing a public URL, run the deployment readiness checker against the
cloud environment file and deployed backend URL. The checker reports variable
names and health status only; it does not print secret values.

```powershell
python tests/performance/deployment_readiness_check.py `
  --env-file backend/.env.production `
  --target cloud `
  --base https://<backend-public-url> `
  --health-path /health `
  --runtime-secret JWT_SECRET_KEY
```

For a public demo without Redis, Milvus, SMTP, OAuth, or real platform keys,
leave those services disabled or unconfigured and verify the UI shows
`not connected` / `configuration required` states instead of fake success.

Public registration remains disabled by default. For a dedicated email
registration validation window only, set both `PUBLIC_REGISTRATION_ENABLED=true`
on the backend and `VITE_PUBLIC_REGISTRATION_ENABLED=true` on the frontend, then
turn both back to `false` after the smoke is complete.

## Database Plan

Use Neon Postgres for the first public demo attempt. Do not upload local SQLite
files or `backend/data/**`.

Initial deployment should use the already committed schema path that is covered by the local quick gates. Alembic migration changes `003-010` remain outside the current public-demo baseline until separately reviewed on a clean database.

Before production data is introduced:

- Run a clean Postgres migration check against an empty managed database.
- Confirm no local test data, customer data, local tokens, or generated reports are imported.
- Record the migration command and result in `docs/public-demo-readiness-2026-08-11.md`.

## Security Settings

Required public settings:

- `ENABLE_PUBLIC_DOCS=false`
- `ENABLE_EVOLUTION_API=false`
- `COOKIE_SECURE=true`
- `CORS_ORIGINS` must be the exact frontend origin, not `*`
- `JWT_SECRET_KEY` must be generated in the deployment platform, not committed
- No default administrator account may be committed or documented with a real password
- External service credentials must be configured through the hosting platform secret store
- `DATABASE_URL`, `JWT_SECRET_KEY`, encryption keys, `SMTP_PASSWORD`, OAuth
  secrets, platform API keys, cookies, and verification codes must not be pasted
  into chat, docs, repository files, logs, screenshots, or reports

Expected behavior when optional services are absent:

- External platforms show `not connected` or `configuration required`
- OAuth status shows missing configuration rather than fake success
- SMTP password reset reports configuration failure clearly
- Milvus/RAG health may be degraded, but must not claim verified live retrieval
- High-risk actions produce drafts or human-review responses only

## Public Smoke Checklist

After deployment, verify and record:

- Frontend URL opens over HTTPS.
- Login page renders.
- Login path succeeds with the approved demo account, or clearly reports that demo login is disabled.
- Chat page opens behind auth.
- Backend `/health` returns JSON.
- Auth failure returns a clear 401/403-style error, not a blank page or stack trace.
- KOL search page renders and shows demo/empty/configuration state correctly.
- Knowledge page renders and shows demo/empty/configuration state correctly.
- Settings / OAuth page shows platform status as `not connected` when credentials are absent.
- No Swagger/OpenAPI docs are publicly exposed in production mode unless explicitly enabled for a private review environment.

Use the HTTP smoke checker for the URL/API layer, then attach browser screenshots
or a short recording for the visual user-path proof:

```powershell
python tests/performance/public_demo_smoke.py `
  --frontend https://<frontend-public-url> `
  --backend https://<backend-public-url>
```

## Forbidden During First Deployment

Do not run the following as part of the first public-demo deployment preparation:

- `docker compose down -v`
- `docker system prune`
- `docker build --no-cache`
- `docker compose up --build`
- Uploading `backend/data/**`
- Committing generated reports, screenshots, or performance artifacts
- Enabling external platform API success paths without real credentials and proof

## Current Status

Completed:

- Display branch is clean.
- Runtime artifacts are not tracked.
- Backend quick gates passed.
- Frontend `npm ci`, Vitest, and build passed.
- README exists.
- Backend and frontend env templates exist.
- Docker low-risk precheck completed without starting containers.

Still required before calling the goal complete:

- Create the selected Vercel, Render, and Neon resources.
- Create cloud resources.
- Configure production environment variables.
- Run managed Postgres migration verification.
- Deploy frontend and backend public URLs.
- Run and document public smoke results.
