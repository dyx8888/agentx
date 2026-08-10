# Public Demo Visual Evidence Plan - 2026-08-11

This plan defines the screenshots and short recording needed after AgentX is
running locally or on public HTTPS URLs. It is a capture checklist only; it does
not prove that public deployment has happened.

## Capture Rules

- Use the clean display branch commit under test.
- Use fictional seed data from `docs/demo-data/`.
- Keep the `Demo data` label visible when demo records are shown.
- Do not show real secrets, cookies, OAuth codes, SMTP passwords, platform API
  keys, private customer names, local database files, or terminal history that
  contains credentials.
- Store generated screenshots under `frontend/screenshots/` or an external
  portfolio/release location.
- Do not commit generated screenshots or recordings unless they are separately
  reviewed and intentionally approved.

## Required Screenshots

| Evidence | Required State | Pass Criteria |
| --- | --- | --- |
| Login page | `/login` over local or public URL | Login UI is visible; no stack trace or blank page |
| Chat page | Authenticated `/` route | Chat surface loads; demo/context wording does not overclaim external execution |
| KOL result | KOL search/result view | Result, empty, or demo state is explicit and does not imply a live platform write |
| Knowledge path | Knowledge entry or state | Upload/read-only/configuration state is visible without frontend crash |
| Settings / OAuth | `/settings` | Platform/OAuth status shows not connected or configuration required when credentials are absent |
| Degraded/error state | Missing external dependency or invalid auth | User-facing error is clear; no backend stack trace or fake success |
| Gate evidence | Terminal or CI summary | Backend gate, frontend Vitest, frontend build, security/pre-push audit evidence is visible |

## Recording Script

Target length: 60-90 seconds.

1. Open the deployed or local demo URL.
2. Show login or controlled demo-login behavior.
3. Open the chat path and send or display a safe demo prompt.
4. Show the KOL path with fictional demo data.
5. Open Settings and show OAuth/platform status as not connected or requiring configuration.
6. Show one guarded/degraded state where the app avoids fake external-platform success.
7. End on a terminal, CI, or README section that states the verified gates and unverified boundaries.

## Evidence Log Template

Use this table in the public smoke record or portfolio release note after
capture. Keep raw media out of Git unless explicitly approved.

| Evidence | Location Or Link | Commit | Date | Result |
| --- | --- | --- | --- | --- |
| Login screenshot | `TBD` | `TBD` | `TBD` | Pending |
| Chat screenshot | `TBD` | `TBD` | `TBD` | Pending |
| KOL screenshot | `TBD` | `TBD` | `TBD` | Pending |
| Knowledge screenshot | `TBD` | `TBD` | `TBD` | Pending |
| Settings / OAuth screenshot | `TBD` | `TBD` | `TBD` | Pending |
| Degraded/error screenshot | `TBD` | `TBD` | `TBD` | Pending |
| Gate evidence screenshot | `TBD` | `TBD` | `TBD` | Pending |
| 60-90 second recording | `TBD` | `TBD` | `TBD` | Pending |

## Current Status

- Visual evidence is planned but not captured.
- Browser screenshots and the recording remain pending external/manual evidence.
- Public demo completion remains blocked on public URLs, managed Postgres
  migration proof, cloud deployment, public smoke, and visual evidence capture.
