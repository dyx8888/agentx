# Public Demo Cloud Handoff - 2026-08-11

This document records the exact handoff needed to move the verified public-demo
branch from local/CI readiness into a real hosted demo. It does not contain
secrets, tokens, production database URLs, or account credentials.

## Verified Input Baseline

- Branch: `codex/public-demo-20260810`
- Current local baseline tag for the next push: `public-demo-local-20260811-v12`
- Last verified remote baseline: `public-demo-local-20260811-v11`
- Last verified remote commit before this cloud-prereq handoff: `9ade535`
- GitHub Actions run `31454147313`: success
  - `backend-quick-gates`: success
  - `frontend-quick-gates`: success
- Render backend Blueprint: `render.yaml`
- Vercel frontend config: `frontend/vercel.json`
- Backend env template: `backend/.env.production.example`
- Frontend env template: `frontend/.env.example`

## Access Required

Codex cannot create the public cloud resources until one of these is available:

- Vercel, Render, and Neon CLI sessions already authenticated on this machine.
- Provider API tokens supplied through process/user environment variables only.
- Manual resources created in the provider UI, with the resulting public URLs
  returned here for verification.

Do not paste secrets into docs, README, issue comments, screenshots, reports,
or committed `.env` files.

## Required Provider Decisions

- Database: Neon Postgres for the first public demo.
- Backend: Render Web Service from repository branch `codex/public-demo-20260810`.
- Frontend: Vercel static deployment from root directory `frontend`.
- Public docs: disabled with `ENABLE_PUBLIC_DOCS=false`.
- Evolution / LoRA routes: disabled with `ENABLE_EVOLUTION_API=false`.
- Optional services: leave unset unless real credentials exist.

## User-Side Cloud Steps

1. Create an empty Neon Postgres database.
2. Store the Neon connection string only in provider secrets or a local shell
   variable used for migration; do not commit it.
3. Create a Render Web Service from the GitHub repo and branch.
4. Use `render.yaml` as the backend Blueprint source.
5. Set Render environment variables:
   - `ENVIRONMENT=production`
   - `ENV=prod`
   - `DATABASE_URL=<Neon URL>`
   - `JWT_SECRET_KEY=<generated secret>`
   - `FRONTEND_URL=https://<vercel-url>`
   - `CORS_ORIGINS=https://<vercel-url>`
   - `COOKIE_SECURE=true`
   - `ENABLE_PUBLIC_DOCS=false`
   - `ENABLE_EVOLUTION_API=false`
6. Create a Vercel project from root directory `frontend`.
7. Set Vercel environment variables:
   - `VITE_API_BASE_URL=https://<render-backend-url>/api`
   - `VITE_DEMO_ENABLED=false`
   - `VITE_DEMO_PASSWORD=`

## Migration Verification

Run the migration against an empty managed Postgres database only:

```powershell
$env:DATABASE_URL = "<managed-postgres-url>"
python backend/scripts/migrate_to_postgres.py
Remove-Item Env:DATABASE_URL
```

If migration fails, stop. Do not upload local SQLite files or `backend/data/**`
as a workaround.

## Evidence To Return

Return only these non-secret values after provider setup:

- Frontend HTTPS URL.
- Backend HTTPS URL.
- Whether Neon migration passed.
- Whether Render `/health` is reachable.
- Whether Vercel build completed.

Do not return `DATABASE_URL`, `JWT_SECRET_KEY`, OAuth secrets, SMTP passwords,
platform API keys, cookies, or screenshots containing secrets.

## Codex Verification After URLs Exist

After URLs are available, Codex should run:

```powershell
python tests/performance/deployment_readiness_check.py `
  --target cloud `
  --base https://<backend-public-url> `
  --health-path /health `
  --runtime-secret JWT_SECRET_KEY

python tests/performance/public_demo_smoke.py `
  --frontend https://<frontend-public-url> `
  --backend https://<backend-public-url>
```

The smoke must prove:

- Frontend home, login, and settings routes return the SPA shell.
- Backend `/health` returns healthy or degraded JSON.
- Invalid login returns a clear authentication error.
- CORS allows only the configured frontend origin.
- `/docs` and `/openapi.json` are not publicly exposed.

## Stop Conditions

Stop before sharing the demo URL if any of these occur:

- Public URL exposes Swagger, OpenAPI, stack traces, debug endpoints, or test
  routes.
- Production CORS uses `*`.
- Missing external platform credentials return fake success.
- A high-risk action claims execution instead of draft or human review.
- Any local database, runtime report, screenshot, or secret file appears in Git.
