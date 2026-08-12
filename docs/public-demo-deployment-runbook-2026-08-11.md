# Public Demo Deployment Runbook - 2026-08-11

This runbook turns the local public-demo baseline into a hosted demo. It is an
execution checklist only. Do not paste real secrets into this file or commit
filled environment files.

## Current Local Baseline

- Branch: `codex/public-demo-20260810`
- Local baseline tag: `public-demo-local-20260811-v15`
- Verify local HEAD before remote push with `git rev-parse --short HEAD`
- Verify the tag points to the same commit with `git rev-list -n 1 --abbrev-commit public-demo-local-20260811-v15`
- Last verified remote branch before this docs refresh: `origin/codex/public-demo-20260810 -> 4d2665b`
- Previous remote baseline tag: `public-demo-local-20260811-v6 -> 4d2665b`; then-current local baseline was `public-demo-local-20260811-v7`
- GitHub Actions `Public Demo Quick Gates`: passed on run `31449945919`
- Last verified remote branch before this deployment-blueprint refresh: `origin/codex/public-demo-20260810 -> 2523d49`
- Previous remote baseline tag: `public-demo-local-20260811-v7 -> 2523d49`; then-current local baseline was `public-demo-local-20260811-v8`
- GitHub Actions `Public Demo Quick Gates`: passed on run `31450691331`
- Last verified remote branch before this cloud-handoff refresh: `origin/codex/public-demo-20260810 -> 7468af6`
- Previous remote baseline tag: `public-demo-local-20260811-v8 -> 7468af6`; then-current local baseline was `public-demo-local-20260811-v9`
- GitHub Actions `Public Demo Quick Gates`: passed on run `31451807722`
- Last verified remote branch before this deployment-audit refresh: `origin/codex/public-demo-20260810 -> 23b3a84`
- Previous remote baseline tag: `public-demo-local-20260811-v9 -> 23b3a84`; then-current local baseline was `public-demo-local-20260811-v10`
- GitHub Actions `Public Demo Quick Gates`: passed on run `31452401665`
- Last verified remote branch before this Docker-precheck refresh: `origin/codex/public-demo-20260810 -> b1f51ec`
- Previous remote baseline tag: `public-demo-local-20260811-v10 -> b1f51ec`; then-current local baseline was `public-demo-local-20260811-v11`
- GitHub Actions `Public Demo Quick Gates`: passed on run `31453473994`
- Last verified remote branch before this cloud-prereq refresh: `origin/codex/public-demo-20260810 -> 9ade535`
- Previous remote baseline tag: `public-demo-local-20260811-v11 -> 9ade535`; current local baseline is `public-demo-local-20260811-v12`
- GitHub Actions `Public Demo Quick Gates`: passed on run `31454147313`
- Last verified remote branch before this completion-prereq refresh: `origin/codex/public-demo-20260810 -> 30cee95`
- Previous remote baseline tag: `public-demo-local-20260811-v12 -> 30cee95`; then-current local baseline was `public-demo-local-20260811-v13`
- GitHub Actions `Public Demo Quick Gates`: passed on run `31454883332`
- Last verified remote branch before this public-smoke trusted-path refresh: `origin/codex/public-demo-20260810 -> 3c69587`
- Previous remote baseline tag: `public-demo-local-20260811-v13 -> 3c69587`; then-current local baseline was `public-demo-local-20260811-v14`
- GitHub Actions `Public Demo Quick Gates`: passed on run `31455582367`
- Last verified remote branch before this startup-degradation refresh: `origin/codex/public-demo-20260810 -> 7402aae`
- Previous remote baseline tag: `public-demo-local-20260811-v14 -> 7402aae`; current local baseline is `public-demo-local-20260811-v15`
- GitHub Actions `Public Demo Quick Gates`: passed on run `31553983717`
- Local worktree status: clean
- Selected deployment path: Vercel frontend, Render backend, Neon Postgres
- Docker full smoke: not run
- Public URL smoke: not run

## Step 1 - Push Display Branch

Only run this after explicitly approving that the branch contents may be sent
to `https://github.com/dyx8888/agentx.git`.

```powershell
git status -sb
git rev-parse --short HEAD
git rev-list -n 1 public-demo-local-20260811-v15
python tests/performance/public_demo_security_audit.py
python tests/performance/public_demo_pre_push_audit.py
git push -u origin codex/public-demo-20260810
git push origin public-demo-local-20260811-v15
```

Optional non-mutating precheck:

```powershell
$env:GIT_TERMINAL_PROMPT = "0"
git push --dry-run origin codex/public-demo-20260810 public-demo-local-20260811-v15
```

If the dry-run hangs or fails because GitHub credentials are unavailable, stop
and authenticate GitHub in a normal PowerShell session before running the real
push. In the Codex environment on 2026-08-11, the non-mutating dry-run failed
with `fatal: User cancelled dialog.` and `fatal: could not read Username for
'https://github.com': terminal prompts disabled`. Do not change branches or
push the original dirty worktree.

HTTPS troubleshooting:

```powershell
Test-NetConnection github.com -Port 443
$env:GIT_TERMINAL_PROMPT = "0"
git ls-remote --heads origin
git ls-remote --heads https://github.com/git/git.git
```

If TCP 443 succeeds but both `ls-remote` commands fail with `Empty reply from
server`, `Failed to connect`, or a timeout, treat it as a local network,
proxy, or GitHub HTTPS transport issue rather than a repository-content issue.

SSH fallback:

```powershell
Test-NetConnection github.com -Port 22
Test-NetConnection ssh.github.com -Port 443
```

If SSH is reachable, configure a GitHub SSH key in a normal PowerShell session
or GitHub Desktop, then use an SSH remote only for this sanitized worktree:

```powershell
git remote set-url origin git@github.com:dyx8888/agentx.git
git push -u origin codex/public-demo-20260810
git push origin public-demo-local-20260811-v15
```

Only do this after the SSH key is added to the GitHub account. Do not create or
commit private keys in this repository.

If GitHub replies with `Permission denied (publickey)`, the SSH transport is
reachable but the account does not have an accepted SSH public key for this
machine. Add the machine's public key to GitHub, or switch back to HTTPS after
fixing Git credential/network access:

```powershell
git remote set-url origin https://github.com/dyx8888/agentx.git
```

If `public_demo_pre_push_audit.py` fails with `runtime artifacts not reachable
in branch history`, stop. Do not push the history-preserving branch to a public
remote. Create or use a sanitized snapshot branch with the same tree and a
clean root history, then rerun the same security and pre-push audits there.

Expected result:

- The remote branch `origin/codex/public-demo-20260810` exists.
- The remote tag `public-demo-local-20260811-v15` exists.
- GitHub Actions can run `.github/workflows/public-demo-quick-gates.yml`.
- No runtime data, reports, screenshots, or `perf_*` artifacts are pushed.

Current result on 2026-08-11:

- Remote branch and `public-demo-local-20260811-v6` existed and both pointed to `4d2665b` before this docs refresh.
- GitHub Actions run `31449945919` passed with both frontend and backend quick gates green.
- Remote branch and `public-demo-local-20260811-v7` existed and both pointed to `2523d49` before this deployment-blueprint refresh.
- GitHub Actions run `31450691331` passed with both frontend and backend quick gates green.
- Remote branch and `public-demo-local-20260811-v8` existed and both pointed to `7468af6` before this cloud-handoff refresh.
- GitHub Actions run `31451807722` passed with both frontend and backend quick gates green.
- Remote branch and `public-demo-local-20260811-v9` existed and both pointed to `23b3a84` before this deployment-audit refresh.
- GitHub Actions run `31452401665` passed with both frontend and backend quick gates green.
- Remote branch and `public-demo-local-20260811-v10` existed and both pointed to `b1f51ec` before this Docker-precheck refresh.
- GitHub Actions run `31453473994` passed with both frontend and backend quick gates green.
- Remote branch and `public-demo-local-20260811-v11` existed and both pointed to `9ade535` before this cloud-prereq refresh.
- GitHub Actions run `31454147313` passed with both frontend and backend quick gates green.
- Remote branch and `public-demo-local-20260811-v12` existed and both pointed to `30cee95` before this completion-prereq refresh.
- GitHub Actions run `31454883332` passed with both frontend and backend quick gates green.
- Remote branch and `public-demo-local-20260811-v13` existed and both pointed to `3c69587` before this public-smoke trusted-path refresh.
- GitHub Actions run `31455582367` passed with both frontend and backend quick gates green.

## Step 2 - Backend Service

Selected provider: Render Web Service.

Settings:

- Root directory: repository root
- Blueprint file: `render.yaml`
- Build command: `python -m pip install --upgrade pip && python -m pip install -r backend/requirements.txt`
- Start command: `PYTHONPATH=backend uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Health check path: `/health`
- Public docs: disabled

Required environment variables:

- `ENVIRONMENT=production`
- `ENV=prod`
- `DATABASE_URL=<managed-postgres-url>`
- `JWT_SECRET_KEY=<generated-in-provider>`
- `FRONTEND_URL=https://<frontend-public-url>`
- `CORS_ORIGINS=https://<frontend-public-url>`
- `COOKIE_SECURE=true`
- `ENABLE_PUBLIC_DOCS=false`
- `ENABLE_EVOLUTION_API=false`

Optional environment variables:

- `REDIS_URL`
- `MILVUS_HOST`
- `MILVUS_PORT=19530`
- `SMTP_HOST`
- `SMTP_PORT=587`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `SMTP_FROM`
- `OAUTH_REDIRECT_BASE_URL=https://<backend-public-url>`
- OAuth, platform API, and model-provider keys

Do not set fake values for optional integrations. Leave them unset unless real
credentials exist, then verify that missing integrations show `not connected`
or `configuration required`.

## Step 3 - Managed Postgres

Selected provider: Neon Postgres.

Rules:

- Use an empty managed Postgres database.
- Do not upload local SQLite files or `backend/data/**`.
- Do not commit the actual `DATABASE_URL`.
- Keep Alembic `003-010` out of the first public demo until separately reviewed.

Verification:

```powershell
$env:DATABASE_URL = "<managed-postgres-url>"
python backend/scripts/migrate_to_postgres.py
```

Record the result in `docs/public-demo-readiness-2026-08-11.md` or a dated
successor document. If migration fails, do not import local data as a shortcut.

## Step 4 - Frontend Static Site

Selected provider: Vercel.

Settings:

- Root directory: `frontend`
- Install command: `npm ci`
- Build command: `npm run build`
- Output directory: `dist`
- Config file: `frontend/vercel.json`

Required environment variable:

- `VITE_API_BASE_URL=https://<backend-public-url>/api`

Optional environment variables:

- `VITE_WS_BASE=wss://<backend-public-url>/ws`
- `VITE_DEMO_ENABLED=false`
- `VITE_DEMO_USERNAME=`
- `VITE_DEMO_PASSWORD=`

Do not enable demo login unless a controlled backend demo account has been
created and documented separately.

## Step 5 - Secret-Safe Preflight

Run this after the backend service is deployed and environment variables are
configured. The checker reports variable names and statuses only; it does not
print secret values.

```powershell
python tests/performance/deployment_readiness_check.py `
  --env-file backend/.env.production `
  --target cloud `
  --base https://<backend-public-url> `
  --health-path /health `
  --runtime-secret JWT_SECRET_KEY
```

If provider secrets are not stored in a local env file, pass their names with
`--runtime-secret` instead of writing values into the repository.

## Step 6 - Public Smoke

Run the HTTP smoke checker against the deployed HTTPS URLs:

```powershell
python tests/performance/public_demo_smoke.py `
  --frontend https://<frontend-public-url> `
  --backend https://<backend-public-url>
```

The smoke must pass before the demo is described as public-ready. It checks:

- HTTPS URL shape
- Frontend `/`, `/login`, and `/settings`
- Backend `/health`
- Invalid login returns a clear auth error
- CORS allows the configured frontend origin
- `/docs` and `/openapi.json` are not publicly exposed

## Step 7 - Manual Browser Evidence

Capture evidence after the HTTP smoke passes:

- Login page
- Chat page after auth
- KOL search result or empty/demo state
- Knowledge upload/read-only/demo state
- Settings / OAuth `not connected` state
- Error/degraded state for an unconfigured external service
- Terminal output for quick gates or smoke

Do not commit generated screenshots or recordings unless they are explicitly
reviewed for secrets and personal data.

## Stop Conditions

Stop and fix before sharing the URL if any of these occur:

- Public 500 stack trace
- Public Swagger/OpenAPI exposure with `ENABLE_PUBLIC_DOCS=false`
- Evolution / LoRA route exposure with `ENABLE_EVOLUTION_API=false`
- Wildcard CORS in production
- Fake success for an unconfigured platform API
- High-risk action claims execution instead of draft/human-review
- Local database, report, screenshot, or secret file appears in Git

## Completion Rule

The project is not a complete public demo until:

- The display branch is pushed.
- Frontend and backend HTTPS URLs exist.
- Managed Postgres migration is verified.
- `public_demo_smoke.py` passes against the public URLs.
- Smoke results are recorded in the public-demo readiness/smoke document.
- Manual browser evidence is captured according to `docs/public-demo-visual-evidence-plan-2026-08-11.md`, including screenshots and a 60-90 second recording or an explicitly documented reason for deferring recording.

