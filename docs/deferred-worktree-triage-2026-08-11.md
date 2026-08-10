# Deferred Worktree Triage - 2026-08-11

This report records the dirty-worktree boundary that remains in the original
local repository after the public-demo branch was split out.

It is a governance artifact only. It does not import, stage, or validate the
dirty files listed here.

## Source State

- Original worktree: `C:\kaifawenjian\agentdianshang`
- Original branch: `codex/local-fixes-20260810`
- Original HEAD when triaged: `9c2c0ad`
- Original staged changes: none
- Original dirty entries: `434`
- Display worktree: `agentdianshang-public-demo`
- Display branch: `codex/public-demo-20260810`
- Display HEAD when triaged: `b6d3701`

The public-demo branch remains the source of truth for the job-demo baseline.
Do not use the original dirty worktree as a deployment source.

## Bucket Summary

| Bucket | Count | Commit Readiness | Action |
| --- | ---: | --- | --- |
| A. Public-demo already closed / no action | 0 | Not applicable | Nothing to submit. |
| B. Later source review candidates | 291 | Not ready | Split by subsystem and review separately. |
| C. Migration / deploy / Docker readiness | 33 | Not ready | Keep outside core demo until provider or Docker proof exists. |
| D. High-risk deferred | 51 | Explicitly deferred | Do not stage into the public-demo branch. |
| E. Runtime data / cache / reports | 16 | Never submit as source | Keep ignored or clean only after explicit approval. |
| F. Suspected unrelated / legacy work | 43 | Not ready | Review only after public-demo release work is complete. |

## A. Public-Demo Already Closed / No Action

Count: `0`

No remaining dirty files in the original worktree are needed to support the
current public-demo baseline. The display branch already carries the trusted
path fixes, frontend dependency completion, quick gates, security audits, demo
docs, env templates, and deployment path decision.

## B. Later Source Review Candidates

Count: `291`

These are broad source changes that may contain useful future work but are not
part of the public-demo baseline. They must be split by subsystem before review.

Representative areas:

- Backend agent and workflow runtime: `backend/app/agent.py`,
  `backend/app/agent_workflow.py`, `backend/app/agents/**`
- Backend communication and orchestration: `backend/app/communication/**`,
  `backend/app/workflow/**`, `backend/app/runtime/**`
- Backend safety and platform surfaces: `backend/app/core/**`,
  `backend/app/platforms/**`, `backend/app/middleware/**`
- Backend RAG and perception: `backend/app/rag/**`,
  `backend/app/perception/**`
- Backend services, tools, tracking, and database internals:
  `backend/app/services/**`, `backend/app/tools/**`,
  `backend/app/tracking/**`, `backend/app/database/**`
- Existing backend test suites and integration suites that are not part of the
  current quick gates
- Frontend current-shell changes such as `frontend/src/components/ChatArea.jsx`,
  `frontend/src/components/ChatInput.jsx`, `frontend/src/components/Sidebar.jsx`,
  `frontend/src/index.css`, `frontend/src/main.jsx`, and `frontend/vite.config.js`

Recommended handling:

- Create separate branches only after the public-demo branch is pushed or
  otherwise safely backed up.
- Review by subsystem, not as one aggregate patch.
- Require focused tests for each subsystem before merging any item back.
- Do not mix these with public deployment, migration, Docker, or old-page
  deletion work.

## C. Migration / Deploy / Docker Readiness

Count: `33`

These files relate to migration, Docker, cloud deployment, requirements, CI, or
environment templates. They are not part of the current display branch.

Representative files:

- `.github/workflows/backend-ci.yml`
- `.github/workflows/evaluation.yml`
- `.dockerignore`
- `backend/.env.example`
- `backend/.env.production.example`
- `backend/DOCKER_DEPLOYMENT.md`
- `backend/Dockerfile`
- `backend/docker-compose.yml`
- `backend/docker-compose.full-smoke.yml`
- `backend/requirements.docker.txt`
- `backend/requirements.lock`
- `backend/railway.json`
- `backend/render.yaml`
- `backend/alembic.ini`
- `backend/alembic/env.py`
- `backend/alembic/versions/001_initial_schema.py`
- `backend/alembic/versions/002_mvp_tables.py`
- `backend/alembic/versions/003_embedding_config.py`
- `backend/alembic/versions/004_p4_cost_audit.py`
- `backend/alembic/versions/005_platform_tokens.py`
- `backend/alembic/versions/006_user_is_active.py`
- `backend/alembic/versions/007_user_bio_llm_usage.py`
- `backend/alembic/versions/008_kol_source_fields.py`
- `backend/alembic/versions/009_user_token_version.py`
- `backend/alembic/versions/010_evolution_log_training_data_path.py`
- `frontend/Dockerfile`
- `frontend/nginx.conf`
- `frontend/.dockerignore`
- `frontend/.env.example`
- `tests/performance/prelaunch_gate_check.py`
- `tests/performance/run_prelaunch_smoke.ps1`
- `tests/performance/start_docker_full_runtime.ps1`

Recommended handling:

- Keep Docker and requirements changes out of the public-demo baseline until a
  Docker or provider-specific build is authorized and verified.
- Do not modify old Alembic migrations without a separate migration review.
- Keep migration `010_evolution_log_training_data_path.py` deferred because it
  is tied to evolution/LoRA and table-name risk.
- Treat CI workflow changes as a separate CI governance patch, not as public
  demo source work.

## D. High-Risk Deferred

Count: `51`

These items have an explicit defer decision and must not be staged into the
public-demo branch without a dedicated branch and review.

Representative files:

- `backend/app/api/evolution.py`
- `backend/app/evolution/**`
- `backend/app/reflection/**`
- Deleted backend debug and scratch scripts:
  `backend/debug_agent.py`, `backend/debug_chat_agent.py`,
  `backend/debug_import.py`, `backend/debug_tools.py`,
  `backend/setup_test_agents.py`, `backend/simple_chat_test.py`,
  `backend/verify_startup.py`
- Deleted or legacy backend tests:
  `backend/tests/test_subscription_api_fixed.py`,
  `backend/tests/test_subscription_api_simple.py`,
  `backend/tests/test_subscription_api_working.py`,
  `backend/tests/test_vector_backend_clean.py`
- Large old frontend page/component deletions:
  `frontend/src/pages/AgentChat.jsx`,
  `frontend/src/pages/AgentConfig.jsx`,
  `frontend/src/pages/AgentCustomize.jsx`,
  `frontend/src/pages/Dashboard.jsx`,
  `frontend/src/pages/Error404.jsx`,
  `frontend/src/pages/Error500.jsx`,
  `frontend/src/pages/Register.jsx`,
  `frontend/src/pages/RegisterPage.jsx`,
  `frontend/src/pages/ReviewWorkflow.jsx`,
  `frontend/src/pages/TaskList.jsx`,
  `frontend/src/components/cards/**`,
  `frontend/src/components/agent-cards.jsx`,
  `frontend/src/components/dashboard-header.jsx`,
  `frontend/src/components/dashboard-sidebar.jsx`,
  `frontend/src/components/login-form.jsx`,
  `frontend/src/components/task-table.jsx`

Recommended handling:

- Evolution/LoRA and reflection require their own review branch.
- Old frontend page deletion requires route inventory, browser smoke, Vitest,
  and production build proof.
- Deleted legacy tests and scratch scripts should be reviewed as cleanup only
  after the public-demo branch is safely remote-backed.

## E. Runtime Data / Cache / Reports

Count: `16`

These files are generated outputs or local artifacts. They should not be
committed as source.

Files and patterns observed:

- `PERFORMANCE_TEST_REPORT.md`
- `backend/.coverage`
- `frontend/screenshots/**`
- `reports/**`
- `tests/reports/**`
- `perf_load_baseline.json`
- `perf_load_optimized.json`
- `perf_load_optimized_v2.json`
- `perf_load_result.json`
- `perf_run.txt`
- `perf_run2.txt`
- `perf_run_optimized.txt`
- `perf_run_optimized_v2.txt`
- `perf_sse_result.json`
- `perf_sse_run.txt`
- Deleted `frontend/test-output.txt`

Recommended handling:

- Keep these ignored for the public-demo branch.
- Clean only after explicit approval.
- If a result is needed for portfolio proof, summarize it in a reviewed
  Markdown document instead of committing generated output.

## F. Suspected Unrelated / Legacy Work

Count: `43`

These files may be useful historically, but they are not directly required for
the current public-demo release path.

Representative areas:

- Backend scratch tests such as `backend/test_chat.py`,
  `backend/test_fastapi_chat.py`, `backend/test_feedback_api.py`,
  `backend/test_streaming_chat.py`, and `backend/test_web_app.py`
- Frontend e2e and Playwright config changes
- Evaluation case changes under `tests/evaluation/cases/**`
- Untracked historic audit docs under `docs/**`
- Load and live-quality test scripts under `tests/performance/**`
- Workspace/local folders such as `kaifawenjian.code-workspace`,
  `scripts/**`, and `sigma/**`

Recommended handling:

- Do not mix with public-demo release commits.
- Review only after P0 public deployment and smoke are complete.
- Move durable audit findings into curated docs only if still relevant and
  currently verified.

## Commit Rules For Future Work

- Never use `git add .` in the original dirty worktree.
- Keep the public-demo branch clean before every push or deployment action.
- Do not stage `backend/data/**`, `reports/**`, `tests/reports/**`,
  `frontend/screenshots/**`, or `perf_*`.
- Keep `backend/app/api/evolution.py`, `backend/app/evolution/**`,
  `backend/app/reflection/**`, old page deletions, Docker full-smoke changes,
  and unreviewed Alembic migration changes outside the public-demo branch.
- Every future commit must be small, named by subsystem, and paired with the
  narrowest relevant gate.

## Next Decision

The public-demo branch is ready for remote backup and hosted deployment work.
The remaining P0 blockers are external-state blockers:

- Push display branch and tag to the approved GitHub remote.
- Create Vercel, Render, and Neon resources.
- Configure production environment variables in provider secret stores.
- Verify managed Postgres migration.
- Run public HTTPS smoke and record results.
