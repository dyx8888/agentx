# Demo Data

This folder contains safe, fictional demo data for portfolio screenshots and public-demo smoke rehearsals.

Rules:

- Do not use real customers, real accounts, real platform tokens, or real private platform exports.
- Keep all names fictional.
- Keep source notes explicit: `Demo data - fictional`.
- Do not upload local SQLite files or `backend/data/**`.
- Do not present these rows as real business evidence.

## Files

- `kol_demo_seed.csv`: fictional KOL rows for the KOL import UI.
- `knowledge_demo_seed.csv`: fictional knowledge rows for the Knowledge import UI.

## Recommended Use

For screenshots or a dry-run rehearsal:

1. Open Settings.
2. Use the KOL or Knowledge import panel.
3. Paste or upload the matching CSV.
4. Prefer `dry run` / validation first.
5. If imported into a temporary demo database, clearly label the environment as `Demo data`.

Do not import these rows into a real production tenant.
