# Project status

> Snapshot of the current state. **Rewrite outdated lines in place** — history belongs in `log/`.
> Last updated: 2026-10-27 by Participant 1 (lab 2 merged and verified on `main`, see `log/2026-10-27-p1-lab2-task-split.md`).

## Current lab: 2 — Stateless architecture

Task lists (Ukrainian, task ids П1-N / П2-N / С-N): [`docs/lab2/participant-1.md`](../lab2/participant-1.md),
[`docs/lab2/participant-2.md`](../lab2/participant-2.md). Their «Домовленості» section (branches, file ownership,
ADR number ranges, ports 8080 / 8082, Redis contract) was followed by both participants.

To avoid merge conflicts, each participant edits **only their own table** below.

### Participant 1

| Task | Status |
|---|---|
| П1-1 Redis + `backend-1` / `backend-2` in compose (branch `lab2/p1-infra`) | ✅ merged into `main` via PR #2 (`78128e9`), ADR 0021 |
| П1-2 Concurrent cold start of two instances on an empty DB (ADR 0009 "Unverified") | ✅ merged via PR #2: 12 simultaneous cold starts all clean, no migrator needed (ADR 0022) |
| П1-3 DataProtection keys → shared store | ✅ merged via PR #4 (ADR 0023) |
| П1-4 State audit: platform modules | ✅ merged via PR #4 |
| П1-5 Cross-instance consistency chain (`requests/cross-instance.http`, `scripts/cross-instance.sh`) | ✅ merged via PR #4; on `main` after PR #3 all 8 steps consistent (step 8 `totalVotes: 1`), README output updated |
| П1-6 C4 component diagram + multi-instance deployment docs | ✅ merged via PR #4; target-state note removed now that the cache is in Redis |
| П1-7 Smoke test on both instances, docs | ✅ merged via PR #4 |

### Participant 2

| Task | Status |
|---|---|
| П2-1 State audit: voting and results modules | ✅ in README «Аудит стану → Голосування й результати» (branch `lab2/p2-voting`) |
| П2-2 "Before" demo: stale results across instances with the in-memory cache (must precede П2-3) | ✅ `scripts/results-cache-demo.py`; stale counts **and** stale 404 after publish, stable in 3 runs; output in README «Усунені in-memory залежності → Кеш результатів» |
| П2-3 `ResultsCache` → Redis (supersedes ADR 0013) | ✅ ADR 0026; demo prints «no» twice (3 runs), same `generatedAt` on both instances; TTL ≤ 10, key gone after a vote; no `IMemoryCache` in `src/` |
| П2-4 Redis unavailable → 503, committed vote not reported as failed | ✅ ADR 0027; `scripts/redis-outage-check.py` (2 runs): results 503, vote 201 stored once, publish 200, recovery without restart. Known cost: ~5 s per Redis-touching request during an outage (lab 4) |
| П2-5 Stateless request flow for `POST /vote` | ✅ in README (table + sequence diagram); matches the code after П2-3 |
| П2-6 The three concurrency checks across two instances | ✅ `scripts/concurrency-checks.py`: green in 4 runs; proven to catch the vote-change race (fails without `FOR UPDATE`) |
| П2-7 Instance-loss test (`docker compose kill` during voting) | ✅ `scripts/kill-test.py`: 3 kill runs + 1 stop run green; PostgreSQL rolled back 1/3/10 open transactions; one retry got 409 (committed, response lost); Docker does not auto-restart after a manual kill |
| П2-8 README sections, docs | ✅ README (audit, before/after, Request Flow, Redis outage, instance loss), runbook, contracts, ADRs 0026–0027; full re-run on a cold start |

### Joint (after all lab 2 branches are merged)

С-1 agree on the proposals · С-2 PR reviews · С-3 consolidated README audit · С-4 code audit (grep for in-process
state) · С-5 cold-start defense rehearsal · С-6 `labs/lab2-summary.md` — all ⏳.

## All labs

| Lab | Status |
|---|---|
| 1 System Design + MVP | 🟡 stages 1–9 done; stage 10 (cold-start defense rehearsal) and `labs/lab1-summary.md` not recorded |
| 2 Stateless | 🟡 all П1/П2 tasks merged into `main` (PR #2, #4, #3) and verified on a cold start; joint tasks С-3…С-6 left |
| 3 Horizontal Scaling | ⏳ (groundwork: `/health`) |
| 4 Distributed Caching | ⏳ |
| 5 Load Testing | ⏳ (groundwork: 500 seed users, hot poll #1) |

## Repository state

- Branch `main`, remote `origin` = https://github.com/totalbyte/highload-system-practice.
- `fix/lab1-review-findings` (review fixes, ADRs 0017–0019, pgAdmin ADR 0020) is merged into `main` via PR #1
  (`06692fe`, 2026-10-21).
- Lab 2 merged into `main` on 2026-10-27: PR #2 `lab2/p1-infra` (`78128e9`), PR #4 `lab2/p1-platform` (`7d6ede8`),
  PR #3 `lab2/p2-voting` (`288534e`). GitGuardian flags the long-standing local-dev default DB password `polling` in
  compose (incident 37528464) — a false positive.
- No branching convention agreed yet; the lab 2 files propose `lab2/p1-infra`, `lab2/p1-platform`, `lab2/p2-voting`.
- No automated tests — verification is the runbook smoke test and the lab 2 scripts in `scripts/`. Last full run on
  `main` 2026-10-27 (cold start): smoke 11/11 on both instances, `cross-instance.sh` 8/8, `results-cache-demo`,
  `concurrency-checks`, `kill-test`, `redis-outage-check` all passed.
- `.gitattributes` keeps LF in the repository. If Git shows whole-file changes after a pull, run
  `git add --renormalize .` and check that `git diff --cached` is empty — then nothing really changed.

## Next steps

- **Lab 2:** both branches merged (PR #4, PR #3); joint tasks next — С-3 audit table, С-4 code audit (Participant 1 leads), С-5 rehearsal, С-6 `labs/lab2-summary.md`.
- **Lab 1 leftovers (if lab 1 is not defended yet):** cold-start defense rehearsal and `labs/lab1-summary.md`.
