# Project status

> Snapshot of the current state. **Rewrite outdated lines in place** — history belongs in `log/`.
> Last updated: 2026-09-22 by Participant 1.

## Current lab: 1 — System Design + MVP

| # | Stage (from the lab 1 execution plan) | Owner | Status |
|---|---|---|---|
| 1 | Skeleton and Docker | Participant 1 | ✅ done |
| 2 | DB schema, migrations, seed | Participant 1 | ✅ done |
| 3 | Auth (JWT): register/login, middleware | Participant 1 | ✅ done |
| 4 | Poll CRUD + validation | Participant 1 | ✅ done (+ `PATCH /publish`, ADR 0002) |
| 5 | `POST /vote`: transaction, 409 on duplicate vote | Participant 2 | ⏳ not started — settle open questions in `contracts.md` first |
| 6 | `GET /results` + in-process cache | Participant 2 | ⏳ not started |
| 7 | Centralized error handler | Participant 2 | 🟡 working minimal version exists (ADR 0005); review, maybe map transient DB errors to 503 |
| 8 | Bottleneck analysis (3+ points) in README | Participant 2 | ⏳ 4-item draft in `project-context.md` |
| 9 | README, OpenAPI, C4, RACI | Both | 🟡 README written; C4 is a basic mermaid diagram |
| 10 | Defense rehearsal (cold start from scratch, all endpoints) | Both | ⏳ |

## All labs

| Lab | Status |
|---|---|
| 1 System Design + MVP | 🟡 in progress |
| 2 Stateless | ⏳ (groundwork: JWT, `X-Instance-ID`, advisory-locked seed) |
| 3 Horizontal Scaling | ⏳ (groundwork: `/health`) |
| 4 Distributed Caching | ⏳ |
| 5 Load Testing | ⏳ (groundwork: 500 seed users, hot poll #1) |

## Repository state

- Branch `main`, remote `origin` = https://github.com/totalbyte/highload-system-practice.
- **All of Participant 1's lab 1 work is uncommitted** in Participant 1's working directory (as of 2026-09-22). Until it is
  pushed, Participant 2 does not have the code.
- No branching / PR convention agreed yet.
- No automated tests yet.

## Next steps

- **Participant 1:** commit and push; agree on a branching convention; after stages 5–6 land, review them and run the
  defense rehearsal together.
- **Participant 2:** settle open questions (`contracts.md` §Open questions) → stage 5 → stage 6 (remove the
  `TODO(Учасник 2)` in `PollService.CloseAsync`) → stage 7 review → stage 8 into README.
