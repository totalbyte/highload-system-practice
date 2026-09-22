# Project status

> Snapshot of the current state. **Rewrite outdated lines in place** — history belongs in `log/`.
> Last updated: 2026-09-22 by Participant 2.

## Current lab: 1 — System Design + MVP

| # | Stage (from the lab 1 execution plan) | Owner | Status |
|---|---|---|---|
| 1 | Skeleton and Docker | Participant 1 | ✅ done |
| 2 | DB schema, migrations, seed | Participant 1 | ✅ done |
| 3 | Auth (JWT): register/login, middleware | Participant 1 | ✅ done |
| 4 | Poll CRUD + validation | Participant 1 | ✅ done (+ `PATCH /publish`, ADR 0002) |
| 5 | `POST /vote`: transaction, 409 on duplicate vote | Participant 2 | ✅ done (ADR 0014, 0015) |
| 6 | `GET /results` + in-process cache | Participant 2 | ✅ done (ADR 0013, 0015) |
| 7 | Centralized error handler | Participant 2 | ✅ done — transient DB errors → 503 (ADR 0016) |
| 8 | Bottleneck analysis (3+ points) in README | Participant 2 | ✅ done — 4 points in README |
| 9 | README, OpenAPI, C4, RACI | Both | 🟡 README and C4 updated (cache shown inside the backend container); Swagger covers all endpoints |
| 10 | Defense rehearsal (cold start from scratch, all endpoints) | Both | ⏳ not done — needs `docker compose down -v` + a full run-through together |

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
- Participant 1's lab 1 work is committed (`4f93a57`).
- **Participant 2's stages 5–8 are uncommitted** in the working directory (as of 2026-09-22).
- No branching / PR convention agreed yet.
- No automated tests yet — verification is the runbook smoke test plus an ad-hoc 40-vote concurrency check.
- **`.gitattributes` added** (2026-09-22, Participant 2): `* text=auto` — LF in the repository, native endings in the
  working copy; `.sln` pinned to CRLF, `.sh` to LF, `.docx` binary. Without it line endings depended on each
  machine's `core.autocrlf`, which eventually shows up as whole-file diffs and needless conflicts. Nothing was
  renormalized: every tracked text file was already stored with LF.

## Next steps

- **Both:** defense rehearsal (stage 10) — `docker compose down -v`, cold start, run `requests/polls.http`
  top to bottom, restart the DB and show the data survived.
- **Participant 1:** review stages 5–8; agree on a branching convention; commit Participant 2's work.
  - **After pulling `.gitattributes`:** if your `core.autocrlf` is not `true`, Git may show working-copy changes
    once. Run `git add --renormalize .` and check that `git diff --cached` is empty — if it is, nothing really
    changed and there is nothing to commit. Please don't delete the file: it is what keeps our diffs clean now that
    two machines write to the same repo.
- **Participant 2:** nothing blocking. When lab 2 starts, the first audit target is `ResultsCache` (ADR 0013)
  and the `DataProtection keys not persisted` warning noted in the runbook.
