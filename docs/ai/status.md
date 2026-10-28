# Project status

> Snapshot of the current state. **Rewrite outdated lines in place** — history belongs in `log/`.
> Last updated: 2026-10-28 by Participant 2 (lab 3 П2-3 … П2-7 on `lab3/p2-experiments` — see `log/2026-10-28-p2-lab3-experiments.md`; Participant 1's П1-3 … П1-7 on `lab3/p1-platform`, PR #8).

## Current lab: 3 — Horizontal scaling

Task lists (Ukrainian, task ids П1-N / П2-N / С-N): [`docs/lab3/participant-1.md`](../lab3/participant-1.md),
[`docs/lab3/participant-2.md`](../lab3/participant-2.md). Load balancer: HAProxy (ADR 0031). Branches `lab3/p1-lb`
(П1-1, П1-2 — merge first, it unblocks Participant 2), `lab3/p1-platform`, `lab3/p2-experiments`; ADR ranges
0031–0035 / 0036–0040.

To avoid merge conflicts, each participant edits **only their own table** below.

### Participant 1

| Task | Status |
|---|---|
| П1-1 HAProxy as the single entry point, backends without ports, `backend-3` in profile `scale` | ✅ merged via PR #7 (`f0566d4`); ADR 0031; verified on a cold start (rotation, :8082 refused, `backend-3` joins without `lb` restart, smoke 11/11 via :8080, live reload `kill -s USR2 lb` with 0 errors) |
| П1-2 Three instances + connection budget for 4+ | ✅ merged via PR #7 (`a6e298c`); ADR 0032 (4+ → `DB_MAX_POOL_SIZE = floor(90 / N)`, `max_connections` stays 100); 5 simultaneous cold starts of three instances clean; 150 threads via lb → peak 90 connections (30 × 3), psql connects. Re-check `pg_stat_activity` ≤ 90 during Participant 2's П2-5 runs |
| П1-3 Active/passive health checks, node exclusion (read path) | ✅ `lab3/p1-platform` (PR open); ADR 0033; `scripts/lb-failover.py`: stop × 2, kill × 2 under a GET stream → 0 non-2xx, node out in 0.3–0.5 s (passive layer4), back ~6–8 s after `start`; DB down → whole pool out in ~4.6 s (HAProxy 503 text/html), back in ~2.3 s. **To settle with Participant 2 (П2-4):** no `observe layer7`, no 5xx retries; vote backend can `track be_api/backend-N` |
| П1-4 Algorithms + live switch + distribution | ✅ `lab3/p1-platform`; ADR 0034; `scripts/lb-algorithm.sh` (validate + SIGUSR2), `scripts/lb-distribution.py`; RR 50/50, LC 53/47, weighted 75/25, source 0/100 (and 3-instance table); RR → LC → RR under `load.py` mixed: 0 5xx |
| П1-5 Lab 2 chain through the balancer | ✅ `lab3/p1-platform`; `cross-instance.sh` / `.http` default to :8080 (8/8, steps split 4/4), `docker-compose.debug.yml` (127.0.0.1:8091–8093) for direct access; `polls.http` already on :8080 |
| П1-6 Architecture diagram, deployment docs, SPOF | ✅ `lab3/p1-platform`; README lab 3 subsections (diagram, deployment, SPOF with Keepalived/VRRP diagram), RACI, repo structure; runbook «Load balancer (lab 3)», contracts |
| П1-7 Close-out | ✅ cold start: smoke 11/11 via :8080, `cross-instance.sh` 8/8, distribution 150/150, kill demo 0 errors; log, ADR index |

### Participant 2

| Task | Status |
|---|---|
| П2-1 Artificial delay on one instance | ✅ merged (PR #6): `Common/Diagnostics/ArtificialDelay.cs`, ADR 0036; 200 ms on `backend-2` → ~215 ms there, `/health` not delayed; off by default |
| П2-2 Load generator | ✅ merged (PR #6): `scripts/load.py`; one process tops out at ≈ 1.8k rps (`read`) — run several in parallel |
| П2-3 RR vs Least Connections with a slow node | ✅ `lab3/p2-experiments` (not merged): RR 50/50, ≈ 300 rps, p95 209 ms; LC 97.5/2.5, ≈ 1.7–2.0k rps, p95 23–28 ms; p99 ≈ 215 ms in both (2.5 % still on the slow node); README |
| П2-4 Node loss during voting | ✅ not merged: `be_vote` in `haproxy.cfg` (ADR 0037) — own checks instead of `track`; `kill-test.py` via the LB: 6 kill + 1 stop runs after a cold start, 0 client errors, DOWN in ≈ 1 s (before: 6 × 502 with П1-3, 52 errors with П1-1); 503 trap verified with `redis-outage-check.py` |
| П2-5 Scale-out 1 / 2 / 3 | ✅ not merged: no CPU limits → flat (one backend served ≈ 5k reads/s); with `cpus: 1` per backend read 1491 / 2785 / 3218 rps, write 108 / 153 / 242 → plateau ≈ 250–300; DB connections 77–79 of 90 on 3 instances (П1-2 criterion) |
| П2-6 Next bottleneck | ✅ not merged: row locks on the hot `vote_count` rows (`Lock` = 26–29 of ≈ 30 active sessions); next — the connection budget for 4+ instances; README |
| П2-7 Lab 2 scripts via the LB, docs | ✅ not merged: `kill-test`, `concurrency-checks`, `redis-outage-check` default to the LB; `results-cache-demo` → `docker-compose.debug.yml`; runbook, contracts, ADR 0037 |

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
| 3 Horizontal Scaling | 🟡 П1-1, П1-2 (PR #7) and П2-1, П2-2 (PR #6) merged; П1-3 … П1-7 on `lab3/p1-platform` (PR open); П2-3 … П2-7 and joint tasks left |
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
  `concurrency-checks`, `kill-test`, `redis-outage-check` all passed. 2026-10-28, `lab3/p1-platform` on a cold
  start: smoke 11/11 through :8080, `cross-instance.sh` 8/8, `lb-distribution.py`, `lb-failover.py --kill` (0 errors).
- Lab 3 merged into `main`: PR #7 `lab3/p1-lb` (П1-1, П1-2), PR #6 `lab3/p2-experiments` (П2-1, П2-2). Branch
  `lab3/p1-platform` (from `main` `65f5ded`): П1-3 … П1-7, PR open.
- `.gitattributes` keeps LF in the repository. If Git shows whole-file changes after a pull, run
  `git add --renormalize .` and check that `git diff --cached` is empty — then nothing really changed.

## Next steps

- **Lab 3, Participant 1:** PR `lab3/p1-platform` (П1-3 … П1-7) → review by Participant 2; agree the
  health-check / retry settings with Participant 2's П2-4 (ADR 0033); then С-2 review of Participant 2's next PR.
- **Lab 3, Participant 2:** П2-3 … П2-7 done on `lab3/p2-experiments` on top of `lab3/p1-platform` (PR #8 must be
  merged first); П2-4 settled: own checks in `be_vote` instead of `track` (ADR 0037, measured). Then С-3 (README
  consolidation, Participant 2 leads), С-4 defense rehearsal, С-5 `labs/lab3-summary.md`.
- **Lab 2:** С-5 cold-start rehearsal and С-6 `labs/lab2-summary.md` (both).
- **Lab 1 leftovers (if lab 1 is not defended yet):** cold-start defense rehearsal and `labs/lab1-summary.md`.
