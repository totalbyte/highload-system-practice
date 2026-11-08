# 0048. Web UI: React SPA behind the same HAProxy
**Status:** Accepted · **Date:** 2026-11-04 · **Author:** Participant 1

## Context
After lab 5 the platform had only Swagger and scripts. A user-facing UI was wanted, styled after a public e-petitions
registry (list of items with a number, author, date, live counter; a detail page with a voting box). Constraints: the
stack must still start with one `docker compose up` and no manual steps; the API and its lab 1–5 behaviour must not change.

## Decision
- **React 19 + Vite + TypeScript**, React Router, TanStack Query (request cache, polling of results every 5 s while a
  poll is open). Hand-written CSS, no UI kit. Vue / Svelte would do the same; Next.js was rejected — SSR is not needed
  and a Node server would be one more component to scale and explain.
- **Delivery:** container `web` (multi-stage: `node:24-alpine` build → `nginx:1.29-alpine`), no host ports. HAProxy
  routes everything except `/api/`, `/swagger`, `/health` to backend `be_web`. One origin (`localhost:8080`) → no CORS
  configuration in the API, and the JWT goes in the `Authorization` header as before.
- `be_web` has no `balance` line and its server is called `web`: `scripts/lb-algorithm.sh` rewrites every
  `    balance` line, and lab 3–5 scripts read `be_api` / `be_vote` rows from the stats page.
- **Favorites in localStorage** (chosen by the participant): no schema change, per-browser only.
- **New endpoint `GET /api/polls/{id}/vote`** — the caller's own vote (200) or 404. Needed to show "your choice" after a
  reload. A plain `AsNoTracking` read by `UNIQUE(poll_id, user_id)`; no cache, no visibility check (a vote can only
  exist in a poll the user could see). Routed to `be_api` (only `POST …/vote` goes to `be_vote`).
- The poll page shows `X-Instance-ID` and `X-Cache` of the results read — a visual aid for the lab 3–4 demos.

## Consequences
- The list page asks `GET /results` per card (10 per page) for the vote counter; almost all are Redis HITs. A list
  endpoint with counters would be the next step if this mattered under load.
- The `web` container is not pinned to cores in the lab 5 load-test environment (ADR 0045); k6 does not touch it, and an
  idle nginx is negligible, but it is one more container on the host during measurements.
