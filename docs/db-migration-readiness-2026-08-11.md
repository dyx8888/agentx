# DB Migration Readiness - 2026-08-11

This document records the database decision and Alembic boundary for the public-demo branch. It does not prove a real managed Postgres migration; that still requires cloud database access.

## Public Demo Database Decision

Use managed Postgres for the public demo.

Do not use or upload:

- Local SQLite files
- `backend/data/**`
- Generated reports
- Local token or credential stores

## Current Tracked Migration Baseline

The display branch currently tracks only:

- `backend/alembic/versions/001_initial_schema.py`
- `backend/alembic/versions/002_mvp_tables.py`

Current migration-related hardening:

- `backend/alembic.ini` uses the intentionally invalid placeholder `driver://user:pass@host/dbname`.
- Alembic must receive the real target through `DATABASE_URL`.
- `backend/scripts/migrate_to_postgres.py` requires an explicit PostgreSQL `DATABASE_URL`.
- The migration script refuses the known weak local default password.
- The migration script no longer prints the full Postgres connection URL.

## 003-010 Migration Boundary

The following candidate migrations are not included in the public-demo baseline:

| Migration | Current Decision | Reason |
| --- | --- | --- |
| `003_embedding_config.py` | Pending separate review | Embedding config changes need clean Postgres migration proof. |
| `004_p4_cost_audit.py` | Pending separate review | Cost/audit schema needs clean Postgres migration proof. |
| `005_platform_tokens.py` | Pending separate review | Platform-token storage must be reviewed with credential handling. |
| `006_user_is_active.py` | Pending separate review | User-state migration needs compatibility review. |
| `007_user_bio_llm_usage.py` | Pending separate review | User/profile and LLM usage fields need compatibility review. |
| `008_kol_source_fields.py` | Pending separate review | KOL source metadata is relevant, but still needs clean DB proof. |
| `009_user_token_version.py` | Pending separate review | Token invalidation field needs auth/session compatibility review. |
| `010_evolution_log_training_data_path.py` | Deferred | Tied to evolution/LoRA area and table-name risk; do not include in public demo baseline. |

## Local Verification

Current local check after hardening:

```powershell
python -m pytest backend/tests/test_postgres_migration.py tests/performance/test_deployment_readiness_check.py -q
```

Result:

- `7 passed, 3 skipped`

The skipped cases require a live Postgres service. They do not prove managed Postgres migration success.

## Required Before Public Completion

Before calling database readiness complete:

- Provision a clean managed Postgres database.
- Set `DATABASE_URL` only in the hosting platform secret store.
- Run the approved migration command against the clean database.
- Record the command, commit, database type, and result in `docs/public-demo-readiness-2026-08-11.md`.
- Do not include migration `003-010` until each has a separate clean review.
