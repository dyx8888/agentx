# Interview Demo Guide - 2026-08-11

This guide is for explaining AgentX as a job-demo project. It should not overstate production readiness or claim live external-platform integrations before public smoke and real credentials are verified.

## 3-Minute Version

AgentX is an AI digital-employee system for ecommerce teams. The demo focuses on trusted user paths: login, chat, KOL search, knowledge workflows, settings, OAuth status, and guarded tool/platform actions.

The engineering problem I focused on was turning a large messy prototype into a reproducible public-demo branch. The key work was separating safe committed fixes from hundreds of dirty local changes, hardening backend trusted paths and tenant boundaries, improving frontend user-path errors and route protection, removing tracked runtime data, and documenting what is verified versus still unverified.

Quality is proven through clean-worktree gates:

- Backend trusted-path/API gate: `39 passed, 85 skipped`
- Backend schema/model/runtime/readiness/public-demo audit gate: `26 passed, 5 skipped, 1 warning`
- Frontend Vitest: `12 passed files / 71 passed tests`
- Frontend production build: passed
- Runtime artifact tracking: `0`
- High-confidence secret scan: `0` hits
- Filled sensitive config placeholders: `0`
- Completion audit: local readiness is checked separately from public URL, managed Postgres, cloud deployment, and screenshot/recording evidence.

The largest engineering challenge was governance: avoiding the temptation to commit every apparent fix. Some changes were deliberately deferred, including evolution/LoRA APIs, old page deletions, Docker full smoke, unreviewed migrations, and real platform integrations. That keeps the demo honest and reviewable.

## 10-Minute Version

### Problem

Ecommerce operators need a unified assistant that can answer business questions, search KOLs, use knowledge context, and prepare operational actions. The hard part is not only generating answers; it is making the system safe enough to demo publicly without fake platform success, leaked data, or broken auth paths.

### Architecture

- React / Vite frontend
- FastAPI backend
- Auth and tenant guard layer
- Chat and conversation APIs
- KOL search APIs
- Knowledge APIs
- Tool/platform adapter layer
- Optional external dependencies: Postgres, Redis, Milvus, OAuth providers, SMTP, platform APIs

### Trusted User Paths

The public demo is intentionally narrow:

- Login or controlled demo-login flow
- Chat page
- KOL search and result display
- Knowledge upload or read-only knowledge state
- Settings / OAuth status display

If external platform credentials are absent, the UI and API must show `not connected` or `configuration required`. High-risk actions must create drafts or require human review; they must not claim that refunds, shipments, outreach, contracts, or platform writes were executed.

### Multi-Tenant And Auth Quality

The backend hardening work focused on trusted paths rather than broad feature expansion. The goal was to make auth, user identity, tenant-scoped data access, KOL behavior, chat behavior, OAuth metadata, and mock fallback policy more reliable for a public demo.

### Test Gates

The gates are intentionally quick and reproducible:

```powershell
python -m pytest tests/api/test_openapi_contract.py backend/tests/test_platform_mock_fallback_policy.py backend/tests/test_health_readiness.py tests/api/test_kol_search.py tests/api/test_production_issue_regressions.py backend/tests/test_rate_limiter_cookie.py backend/tests/test_admin_production_mock_policy.py -q
```

```powershell
python -m pytest backend/tests/test_postgres_migration.py backend/tests/test_model_gateway_tokenrhythm.py backend/tests/test_runtime_eval_mode.py backend/tests/test_public_demo_route_scope.py tests/performance/test_deployment_readiness_check.py tests/performance/test_public_demo_smoke.py tests/performance/test_public_demo_pre_push_audit.py tests/performance/test_public_demo_security_audit.py tests/performance/test_public_demo_completion_audit.py -q
```

```powershell
cd frontend
npm.cmd ci
npm.cmd run test -- --run
npm.cmd run build
```

### Public Deployment Boundary

The current branch is a public-demo candidate, not a fully proven production system. The next required proof is public deployment and smoke:

- HTTPS frontend URL opens
- Backend `/health` returns JSON
- Auth path works or fails clearly
- Chat page opens
- KOL and knowledge paths show safe demo/configuration states
- Missing external platform credentials do not produce fake success

### Deferred Work

These are intentionally outside the current demo branch:

- Evolution / LoRA APIs
- Reflection/runtime evaluation expansion
- Large old frontend page deletions
- Alembic migration chain changes `003-010`
- Docker full runtime smoke
- Real Milvus quality proof
- Real OAuth / SMTP / platform API proof

## Screenshot And Recording Plan

Capture these after a real local or public smoke run:

- Login page
- Chat page
- KOL search results
- Settings / OAuth status
- External API degraded state such as `not connected`
- Terminal summary showing quick gates passed

Recommended recording:

- Length: 60-90 seconds
- Flow: open demo URL, login, open chat, show KOL path, show settings/OAuth status, mention verified gates and unverified boundaries
- Do not show real secrets, local database files, tokens, or private customer data

## Claims To Avoid

Do not say:

- All ecommerce platforms are production-integrated.
- Real OAuth and SMTP are proven.
- Milvus/RAG quality is proven in public deployment.
- Docker full runtime is verified.
- The project is production-ready for public users.

Safer wording:

- Public-demo candidate
- Trusted user paths are locally verified
- External integrations are designed to fail closed or show configuration-required states
- Real cloud smoke remains the next proof step


