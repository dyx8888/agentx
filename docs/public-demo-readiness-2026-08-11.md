# Public Demo Readiness - 2026-08-11

This document records the current public-demo readiness state for AgentX.

## Branch And Scope

- Display branch: `codex/public-demo-20260810`
- Sanitized snapshot is a clean-root public display branch; verify the current commit with `git rev-parse --short HEAD`
- Current local baseline anchor: `public-demo-local-20260811-v12`
- Verify tag target before push: `git rev-list -n 1 public-demo-local-20260811-v12`
- Latest backend/frontend gate evidence: sanitized snapshot candidate
- Latest local audit evidence: sanitized snapshot candidate
- Goal: a public, reproducible, job-demo-ready AgentX demo without local runtime data or real credentials.
- Original dirty worktree: intentionally excluded from this branch; remaining historical changes must continue to be reviewed in small batches.

## Minimum Public Demo Surface

The public demo scope is limited to:

- Login / register or a clearly marked demo-login flow
- Chat user path
- KOL search and result display
- Knowledge upload or read-only sample knowledge state
- Settings / OAuth status display

Out of scope for the first public demo:

- Real external platform execution
- Real OAuth provider proof
- Real SMTP delivery
- Real Milvus-backed RAG proof
- Evolution / LoRA APIs, disabled by default in production public-demo config with `ENABLE_EVOLUTION_API=false`
- Docker full smoke

## Safety Rules

- External platform APIs must show `not connected` / `configuration required` when credentials are absent.
- Mock fallback must not report fake success in production-like paths.
- High-risk actions must produce a draft or human-review response, not claim that a shipment, refund, outreach, contract, or platform write action was executed.
- Local databases, vector stores, reports, screenshots, and performance artifacts must stay out of Git.

## Completed Public-Readiness Commits

- `25d7526 fix: include token blacklist dependency`
- `96a892c fix: export active agent registry`
- `f788865 fix: include high risk action guard`
- `5c1b77d fix: expose oauth credential metadata`
- `9c2c0ad chore: stop tracking runtime data artifacts`
- `57f8857 fix: harden public demo production config`
- `34f0467 chore: ignore pytest runtime cache`
- `1125b51 docs: add public demo readiness record`
- `2dc1522 docs: add public demo README`
- `0442c61 docs: update public demo verification record`
- `b07f2a7 chore: add frontend demo env template`
- `7cd9a02 docs: add public demo deployment plan`
- `4383e3a docs: add public demo interview and smoke guides`
- `7fc75bc docs: add safe public demo data samples`
- `7f54c1a chore: harden public demo database defaults`
- `036c245 ci: add public demo quick gates`
- `652ce4e docs: add public demo security review`
- `f3418b0 docs: refresh public demo gate evidence`
- `b7331f9 chore: add public demo deployment templates`
- `3987ba6 fix: disable admin mock fallback in production`
- `18bf266 docs: record docker low-risk precheck`
- `1605264 test: align deployment readiness preflight`
- `85c454e test: add public demo smoke checker`
- `1ce75dc docs: record public smoke checker evidence`
- `8b08fcb docs: add public demo deployment runbook`
- `ce4dfba docs: record local public demo baseline tag`
- `5e2631b docs: make public demo baseline tag authoritative`
- `8dc58a7 test: add public demo pre-push audit`
- `568ce74 test: add public demo security audit`
- `2fa89b9 test: strengthen public demo secret audit`
- `bb5b279 test: add public demo completion audit`
- `8e7246a ci: include public demo completion audit`
- `73079a3 test: expand public demo smoke route coverage`
- `61021ac test: align completion audit with smoke coverage`
- `57f236c docs: refresh smoke coverage evidence`
- `8ab32f3 docs: add public demo visual evidence plan`
- `68855f0 docs: refresh public demo precheck evidence`
- `915ac1f test: require visual evidence plan in public demo audit`
- `f15381b test: guard public demo CI pre-push scope`
- `7c7f2e0 test: audit public demo deployment templates`
- `61a2cf1 docs: refresh public demo gate evidence`
- `8235444 docs: require visual evidence before public completion`
- `64e448f test: mark public branch push as external completion gate`
- `6362ae4 chore: prevent compose precheck secret leakage`
- `ccb9227 docs: refresh public demo precheck evidence`
- `9ba3c3f docs: clarify public demo precheck evidence anchor`
- `d74088d docs: record ssh push publickey blocker`
- `b24292c ci: stabilize public demo quick gates`
- `324119c ci: align public demo quick gates runtime`
- `7e7b8b9 ci: split backend public demo gates`
- `bc7153d ci: isolate backend runtime gate steps`
- `4d2665b test: make public demo route scope gate deterministic`
- `2523d49 docs: record public demo ci push evidence`
- `7468af6 chore: add render blueprint for public demo`
- `23b3a84 docs: add public demo cloud handoff`
- `b1f51ec test: add deployment template audit`

## Verified Evidence

Remote public-demo evidence:

- Before this docs refresh, branch `origin/codex/public-demo-20260810` pointed to `4d2665b`.
- Previous tag `public-demo-local-20260811-v6` pointed to `4d2665b`; then-current local baseline tag was `public-demo-local-20260811-v7`.
- GitHub Actions run `31449945919` completed successfully on code baseline `4d2665b`.
  - `frontend-quick-gates`: success
  - `backend-quick-gates`: success
- Before this deployment-blueprint refresh, branch `origin/codex/public-demo-20260810` pointed to `2523d49`.
- Previous tag `public-demo-local-20260811-v7` pointed to `2523d49`; then-current local baseline tag was `public-demo-local-20260811-v8`.
- GitHub Actions run `31450691331` completed successfully on code baseline `2523d49`.
  - `frontend-quick-gates`: success
  - `backend-quick-gates`: success
- Before this cloud-handoff refresh, branch `origin/codex/public-demo-20260810` pointed to `7468af6`.
- Previous tag `public-demo-local-20260811-v8` pointed to `7468af6`; then-current local baseline tag was `public-demo-local-20260811-v9`.
- GitHub Actions run `31451807722` completed successfully on code baseline `7468af6`.
  - `frontend-quick-gates`: success
  - `backend-quick-gates`: success
- Before this deployment-audit refresh, branch `origin/codex/public-demo-20260810` pointed to `23b3a84`.
- Previous tag `public-demo-local-20260811-v9` pointed to `23b3a84`; then-current local baseline tag was `public-demo-local-20260811-v10`.
- GitHub Actions run `31452401665` completed successfully on code baseline `23b3a84`.
  - `frontend-quick-gates`: success
  - `backend-quick-gates`: success
- Before this Docker-precheck refresh, branch `origin/codex/public-demo-20260810` pointed to `b1f51ec`.
- Previous tag `public-demo-local-20260811-v10` pointed to `b1f51ec`; then-current local baseline tag was `public-demo-local-20260811-v11`.
- GitHub Actions run `31453473994` completed successfully on code baseline `b1f51ec`.
  - `frontend-quick-gates`: success
  - `backend-quick-gates`: success
- Before this cloud-prereq refresh, branch `origin/codex/public-demo-20260810` pointed to `9ade535`.
- Previous tag `public-demo-local-20260811-v11` pointed to `9ade535`; current local baseline tag is `public-demo-local-20260811-v12`.
- GitHub Actions run `31454147313` completed successfully on code baseline `9ade535`.
  - `frontend-quick-gates`: success
  - `backend-quick-gates`: success
- `tests/performance/public_demo_completion_audit.py` now reports the display
  branch push check as `PASS`, while keeping public URL, public smoke, managed
  Postgres migration, cloud deployment, and browser evidence as external
  pending items.

Clean backend verification evidence in `agentdianshang-public-demo`:

- `python -m pytest tests/api/test_openapi_contract.py backend/tests/test_platform_mock_fallback_policy.py backend/tests/test_health_readiness.py tests/api/test_kol_search.py tests/api/test_production_issue_regressions.py backend/tests/test_rate_limiter_cookie.py backend/tests/test_admin_production_mock_policy.py -q`
  - Result on sanitized snapshot: `39 passed, 85 skipped, 1 warning`
- `python -m pytest backend/tests/test_postgres_migration.py backend/tests/test_model_gateway_tokenrhythm.py backend/tests/test_runtime_eval_mode.py backend/tests/test_public_demo_route_scope.py tests/performance/test_deployment_readiness_check.py tests/performance/test_public_demo_smoke.py tests/performance/test_public_demo_deployment_template_audit.py tests/performance/test_public_demo_cloud_prereq_audit.py tests/performance/test_public_demo_pre_push_audit.py tests/performance/test_public_demo_security_audit.py tests/performance/test_public_demo_completion_audit.py -q`
  - Result on sanitized snapshot: `48 passed, 5 skipped, 1 warning`
- `tests/performance/public_demo_completion_audit.py` separates `local_ready`
  from `public_complete`, so public URL, managed Postgres, cloud deployment,
  public smoke, and screenshot/recording evidence remain explicit pending
  external items.
- `tests/performance/public_demo_deployment_template_audit.py` checks `render.yaml`, `frontend/vercel.json`, `backend/.env.production.example`, and `frontend/.env.example`.
  - It verifies Render build/start/health settings, production safety toggles, `sync:false` runtime secrets, Vercel SPA rewrites, blank production secrets, and disabled frontend demo password.
- `tests/performance/public_demo_cloud_prereq_audit.py` checks local cloud deployment prerequisites without provider API calls.
  - Missing Vercel, Render, Neon, or production runtime credentials are recorded as `pending_external`; unsafe public CORS fails the audit.
- Deployment readiness preflight on `1605264`:
  - `tests/performance/deployment_readiness_check.py` now probes `/health`, matching the backend and Render template
  - Redis, Milvus, SMTP, OAuth, platform API, and model-provider keys are optional/degraded checks, not P0 blockers when intentionally unconfigured for the public demo
- Public demo HTTP smoke checker on `73079a3`:
  - `tests/performance/public_demo_smoke.py` verifies HTTPS URL shape, frontend `/`, `/login`, and `/settings`, backend `/health`, invalid auth failure, CORS preflight, and disabled public docs after URLs exist
  - `tests/performance/test_public_demo_smoke.py` passed as part of the expanded readiness gate
- Production config import check on `3987ba6`:
  - `docs_url=None` and `openapi_url=None` when `ENABLE_PUBLIC_DOCS=false`
  - `CORS_ALLOW_ORIGINS=['https://demo.example.com']` from `backend/app/main.py`
  - `_is_production()` returns `True`
  - Redis and Milvus were unavailable locally and surfaced as degraded warnings, not startup blockers

Frontend clean verification was rerun on sanitized snapshot:

- `npm.cmd ci`
  - Result: installed `374 packages`
- `npm.cmd run test -- --run`
  - Result: `12 passed files / 71 passed tests`
- `npm.cmd run build`
  - Result: succeeded
- Note: the first sandboxed build attempt hit a local filesystem permission error while resolving `vite.config.js`; the same command passed when rerun with normal workspace permissions.

## Public Security Checks

Current sanitized snapshot scan:

- Tracked runtime artifact count: `0`
- High-confidence secret pattern hits: `0`
- Filled sensitive config placeholder count: `0`
- `backend/data/**`, `backend/.coverage`, reports, screenshots, and `perf_*` are ignored and not tracked.
- The pre-push audit now checks both the current tree and branch history for
  runtime artifacts. A history-preserving branch that still reaches old
  `backend/data/**` or `backend/.coverage` objects must not be pushed as the
  public display branch; use a sanitized snapshot branch with the same tree.
- `tests/performance/public_demo_security_audit.py` passed as part of the expanded readiness gate.

Production config behavior:

- `ENVIRONMENT=production`, `ENV=prod`, and `FRONTEND_URL=https://demo.example.com`:
  - `docs_url=None`
  - `openapi_url=None`
  - `CORS_ALLOW_ORIGINS=['https://demo.example.com']`
- `ENVIRONMENT=production` with `CORS_ORIGINS=*`:
  - Import fails closed with `RuntimeError: CORS_ORIGINS cannot contain '*' in production`
- Cookie Secure detection now recognizes `ENVIRONMENT=production`.
- Evolution / LoRA API routes and background services are disabled by default when `ENABLE_EVOLUTION_API=false`.
- `backend/.env.production.example` exists and contains required variables without filled secrets.
- `frontend/.env.example` exists and contains only public Vite configuration placeholders.

## Docker Low-Risk Precheck

Low-risk precheck was rerun on `2026-08-11` before the v11 baseline.
No containers were started, no images were built, and no Docker volumes were
deleted.

- `docker --version`: Docker `29.6.2`
  - Docker daemon connection was not available: `docker_engine` pipe not found
  - Current user also cannot read `C:\Users\win\.docker\config.json`
- `docker compose version`: Compose `v5.3.1`
- `docker --config $env:TEMP compose -f backend/docker-compose.yml config`: passed without starting
  containers
  - Rendered `DEEPSEEK_API_KEY` values are blank, so host shell API keys are not
    leaked by low-risk precheck output
  - Warning: Compose `version` field is obsolete
  - Warning: Docker config file access warning in the current user environment
- Port check:
  - `3000`, `5173`, `8000`, `5432`, `6379`, `8101`, `8104`, `9001`, `19530` not listening
- Disk check:
  - `C:\`: `85.56 GB` free
  - `D:\`: `21.25 GB` free
  - `Q:\`: `37.50 GB` free
- Environment/template existence check:
  - `backend/.env` and `frontend/.env`: ignored local files, not tracked
  - `backend/.env.production.example`: present
  - `frontend/.env.example`: present
  - `backend/docker-compose.yml`: present
  - `frontend/vercel.json`: present
  - `deploy/render.example.yaml`: present
  - `render.yaml`: present as the root Render Blueprint for the backend web service
  - `docs/public-demo-cloud-handoff-2026-08-11.md`: present as the secret-safe handoff checklist for provider setup

## Not Yet Proven

The following remain unverified and must not be described as complete:

- Public URL deployment
- HTTPS domain
- Public smoke test
- Real Postgres migration on a managed database
- Real Milvus connectivity and RAG query quality
- Real OAuth provider callbacks
- Real SMTP password reset delivery
- Real external platform APIs
- Docker full runtime smoke
- VHDX / Docker Desktop full environment

## Deferred Items

Do not mix these into the public demo branch without separate review:

- `backend/app/api/evolution.py`
- `backend/app/evolution/**`
- `backend/app/reflection/**`
- Evolution / LoRA API changes
- Large old frontend page/component deletions
- Alembic migration chain changes
- Docker/requirements/deployment rewrites
- Runtime data, reports, screenshots, and performance outputs

## Next Recommended Step

The sanitized display branch is pushed and GitHub Actions quick gates are
green. The selected deployment path remains Vercel frontend, Render backend,
and Neon Postgres.

Next required external step:

1. Create/configure Neon Postgres and run the managed database migration.
2. Deploy the Render backend with production environment variables.
3. Deploy the Vercel frontend with `VITE_API_BASE_URL` pointing to Render.
4. Run `tests/performance/public_demo_smoke.py` after HTTPS URLs exist.
5. Capture browser screenshots/recording according to the visual evidence plan.

Historical GitHub connectivity diagnostics before the successful SSH push:

- Codex attempted local `git push --dry-run` prechecks on 2026-08-11. The first
attempt produced no remote result after about 90 seconds and was aborted. A
second non-mutating dry-run with `GIT_TERMINAL_PROMPT=0` failed with
`fatal: User cancelled dialog.` and `fatal: could not read Username for
'https://github.com': terminal prompts disabled`. No remote writes were made by
either dry-run attempt.

- `Test-NetConnection github.com -Port 443`: TCP succeeded.
- `git ls-remote --heads origin`: failed with `Empty reply from server`.
- `git -c http.version=HTTP/1.1 ls-remote --heads origin`: failed to connect.
- `git ls-remote --heads https://github.com/git/git.git`: failed to connect.
- `Invoke-WebRequest https://github.com`: timed out.
- `Test-NetConnection github.com -Port 22`: TCP succeeded.
- `Test-NetConnection ssh.github.com -Port 443`: TCP succeeded.
- `gh` CLI is not installed in the Codex environment.
- `%USERPROFILE%\.ssh` is not present in the Codex environment.
- A normal PowerShell SSH push attempt accepted GitHub's ED25519 host key but
  failed with `git@github.com: Permission denied (publickey).`
- A later normal PowerShell SSH push succeeded after SSH access was available;
  the current remote is `git@github.com:dyx8888/agentx.git`.

Do not describe the project as fully complete until a public URL, HTTPS configuration, and public smoke test are verified.




