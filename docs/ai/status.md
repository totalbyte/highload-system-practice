# Project status

> Snapshot of the current state. **Rewrite outdated lines in place** — history belongs in `log/`.
> Last updated: 2026-10-28 by Participant 1 (lab 3 П1-1 and П1-2 committed on `lab3/p1-lb`, not pushed — see `log/2026-10-28-p1-lab3-lb.md`).

## Current lab: 3 — Horizontal scaling

Task lists (Ukrainian, task ids П1-N / П2-N / С-N): [`docs/lab3/participant-1.md`](../lab3/participant-1.md),
[`docs/lab3/participant-2.md`](../lab3/participant-2.md). Load balancer: HAProxy (ADR 0031). Branches `lab3/p1-lb`
(П1-1, П1-2 — merge first, it unblocks Participant 2), `lab3/p1-platform`, `lab3/p2-experiments`; ADR ranges
0031–0035 / 0036–0040.

To avoid merge conflicts, each participant edits **only their own table** below.

### Participant 1

| Task | Status |
|---|---|
| П1-1 HAProxy as the single entry point, backends without ports, `backend-3` in profile `scale` | ✅ `f0566d4` on `lab3/p1-lb` (not pushed, no PR yet); ADR 0031; verified on a cold start (rotation, :8082 refused, `backend-3` joins without `lb` restart, smoke 11/11 via :8080, live reload `kill -s USR2 lb` with 0 errors) |
| П1-2 Three instances + connection budget for 4+ | ✅ `a6e298c` on `lab3/p1-lb`; ADR 0032 (4+ → `DB_MAX_POOL_SIZE = floor(90 / N)`, `max_connections` stays 100); 5 simultaneous cold starts of three instances clean; 150 threads via lb → peak 90 connections (30 × 3), psql connects. Re-check `pg_stat_activity` ≤ 90 during Participant 2's П2-5 runs |
| П1-3 Active/passive health checks, node exclusion (read path) | ⏳ — known gap until then: ~8 s hang + HAProxy 503 right after a node disappears (ADR 0031) |
| П1-4 Algorithms + `lb-distribution` script | ⏳ (reload command already verified) |
| П1-5 Lab 2 chain (`cross-instance.*`, `polls.http`) through the balancer | ⏳ — `cross-instance.sh` still targets :8082 |
| П1-6 Architecture diagram, deployment docs, SPOF | ⏳ (README skeleton for lab 3 with owners is in place) |
| П1-7 Close-out | ⏳ |

### Participant 2

| Task | Status |
|---|---|
| П2-1 … П2-7 | ⏳ not started; П2-1 / П2-2 do not depend on the balancer. Python scripts still default to :8082 (П2-7) |

### Lab 3 — Participant 2 (branch `lab3/p2-experiments`; task split in PR #5)

| Task | Status |
|---|---|
| П2-1 Artificial delay on one instance | ✅ `Common/Diagnostics/ArtificialDelay.cs`, ADR 0036; 200 ms on `backend-2` → ~215 ms there vs ~20 ms on `backend-1`, `/health` not delayed; off by default (smoke 9/9 on both) |
| П2-2 Load generator | ✅ `scripts/load.py` (read / write / mixed, p50/p95/p99, split by `X-Instance-ID`, counter check); 3 runs each: read spread 4 %, write 20 %, counters 0 |
| П2-3 … П2-7 | ⏳ need the load balancer (`lab3/p1-lb`, Participant 1) |

### Joint (after all lab 2 branches are merged)

| Task | Status |
|---|---|
| С-1 Confirm the agreements and HAProxy | ⏳ both (Participant 1 started П1-1 on the proposal) |
| С-2 … С-5 | ⏳ |

### Lab 2 leftovers

All П1/П2 tasks of lab 2 are merged (PR #2, #4, #3) and were verified on 2026-10-27; С-1…С-4 done. Left: С-5
cold-start defense rehearsal and С-6 `labs/lab2-summary.md` (both). Note: since П1-1 of lab 3 the lab 2 demos that
address `backend-2` on :8082 need the lab 3 versions (П1-5 / П2-7) or a `docker-compose.debug.yml`.

## All labs

| Lab | Status |
|---|---|
| 1 System Design + MVP | 🟡 stages 1–9 done; stage 10 (cold-start defense rehearsal) and `labs/lab1-summary.md` not recorded |
| 2 Stateless | 🟡 all П1/П2 tasks merged into `main` (PR #2, #4, #3) and verified on a cold start; joint tasks С-5, С-6 left |
| 3 Horizontal Scaling | 🟡 task split merged (PR #5); П1-1, П1-2 on `lab3/p1-lb` (ADRs 0031–0032), PR pending |
| 4 Distributed Caching | ⏳ |
| 5 Load Testing | ⏳ (groundwork: 500 seed users, hot poll #1) |

## Repository state

- Branch `main`, remote `origin` = https://github.com/totalbyte/highload-system-practice.
- `fix/lab1-review-findings` (review fixes, ADRs 0017–0019, pgAdmin ADR 0020) is merged into `main` via PR #1
  (`06692fe`, 2026-10-21).
- Lab 2 merged into `main` on 2026-10-27: PR #2 `lab2/p1-infra` (`78128e9`), PR #4 `lab2/p1-platform` (`7d6ede8`),
  PR #3 `lab2/p2-voting` (`288534e`). GitGuardian flags the long-standing local-dev default DB password `polling` in
  compose (incident 37528464) — a false positive.
- No branching convention agreed yet; lab 2 used `lab2/p1-infra`, `lab2/p1-platform`, `lab2/p2-voting`, the lab 3
  files propose `lab3/p1-lb`, `lab3/p1-platform`, `lab3/p2-experiments`.
- No automated tests — verification is the runbook smoke test and the lab 2 scripts in `scripts/`. Last full run on
  `main` 2026-10-27 (cold start): smoke 11/11 on both instances, `cross-instance.sh` 8/8, `results-cache-demo`,
  `concurrency-checks`, `kill-test`, `redis-outage-check` all passed. 2026-10-28, uncommitted lab 3 П1-1 tree (cold
  start): smoke 11/11 through the balancer on :8080; the lab 2 scripts were not re-run (they still target :8082).
- Branch `lab3/p1-lb` (local, not pushed): П1-1 `f0566d4`, П1-2 `a6e298c`.
- `.gitattributes` keeps LF in the repository. If Git shows whole-file changes after a pull, run
  `git add --renormalize .` and check that `git diff --cached` is empty — then nothing really changed.

## Next steps

- **Lab 3, Participant 1:** push `lab3/p1-lb` → PR into `main` → review by Participant 2. Then `lab3/p1-platform`: П1-3 → П1-7.
- **Lab 3, Participant 2:** П2-1, П2-2 can start now; after `lab3/p1-lb` is merged, the rest goes through :8080.
- **Lab 2:** С-5 cold-start rehearsal and С-6 `labs/lab2-summary.md` (both).
- **Lab 1 leftovers (if lab 1 is not defended yet):** cold-start defense rehearsal and `labs/lab1-summary.md`.
