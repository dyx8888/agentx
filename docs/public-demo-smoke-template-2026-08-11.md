# Public Demo Smoke Template - 2026-08-11

Use this file after the public frontend and backend URLs are deployed. Do not mark any item passed until it is verified against the public HTTPS URLs.

## Deployment Under Test

- Frontend URL: `TBD`
- Backend URL: `TBD`
- Backend commit: `TBD`
- Frontend commit: `TBD`
- Test date/time: `TBD`
- Tester: `TBD`

## Required Public Smoke Results

Run the automated HTTP smoke first:

```powershell
python tests/performance/public_demo_smoke.py `
  --frontend https://<frontend-public-url> `
  --backend https://<backend-public-url>
```

| Check | Expected Result | Actual Result | Status |
| --- | --- | --- | --- |
| Frontend opens over HTTPS | Page loads without certificate or mixed-content errors | `TBD` | Pending |
| Login page renders | Login UI is visible and usable | `TBD` | Pending |
| Login or demo-login path | Approved demo account works, or demo login is clearly disabled | `TBD` | Pending |
| Protected route behavior | Unauthenticated access redirects or returns a clear auth error | `TBD` | Pending |
| Chat page opens | Chat surface loads after auth | `TBD` | Pending |
| Backend health | `GET /health` returns JSON | `TBD` | Pending |
| Auth failure | Invalid credentials return a clear 401/403-style error | `TBD` | Pending |
| KOL search page | Shows result, empty, or demo/configuration state without fake success | `TBD` | Pending |
| Knowledge page | Shows upload/read-only/demo/configuration state without blank page | `TBD` | Pending |
| Settings / OAuth page | Shows platform status as `not connected` when credentials are absent | `TBD` | Pending |
| External platform action | Missing credentials do not produce fake execution success | `TBD` | Pending |
| High-risk action | Produces draft or human-review state, not executed-state claim | `TBD` | Pending |
| Swagger/OpenAPI exposure | Public production mode does not expose docs unless intentionally enabled | `TBD` | Pending |

## Evidence To Attach

Record evidence paths or public links after testing:

- Login screenshot: `TBD`
- Chat screenshot: `TBD`
- KOL screenshot: `TBD`
- Settings / OAuth screenshot: `TBD`
- Error/degraded-state screenshot: `TBD`
- Terminal or CI output for quick gates: `TBD`
- Optional 60-90 second recording: `TBD`

Generated screenshots and recordings should not be committed to the repository unless explicitly reviewed. Prefer attaching them to the portfolio page, release note, or external demo record.

## Failure Rules

Treat the public smoke as failed if any of the following occur:

- Blank page or uncaught frontend error on first load
- Public 500 stack trace
- Real-looking success for an unconfigured platform API
- High-risk action claims execution without a human-review step
- Public docs exposed unexpectedly in production mode
- CORS blocks the frontend from using the backend
- Auth cookie behavior fails over HTTPS

## Final Smoke Decision

- Overall status: `Pending`
- Decision: `Do not call public demo complete until all P0 smoke checks pass.`
- Follow-up issues: `TBD`
