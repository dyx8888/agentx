# Deployment Templates

This folder contains public-demo deployment templates only. They do not create cloud resources by themselves and they do not contain real secrets.

Use these templates after choosing the actual hosting providers:

- `frontend/vercel.json`: Vercel static frontend configuration.
- `deploy/render.example.yaml`: Render backend service example.

Before deploying:

- Set real values in the hosting platform secret store.
- Keep `ENABLE_PUBLIC_DOCS=false`.
- Keep `COOKIE_SECURE=true`.
- Set exact `FRONTEND_URL` and `CORS_ORIGINS`.
- Do not upload `backend/data/**` or generated reports.
- Record final public smoke results in `docs/public-demo-smoke-template-2026-08-11.md` or a completed successor document.
