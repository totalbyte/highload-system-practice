# Project status

> Snapshot of the current state. **Rewrite outdated lines in place** — history belongs in `log/`.
> Last updated: 2026-11-02 by Participant 1 (lab 4 П1-1 … П1-3 done, not committed — see `log/2026-11-02-p1-lab4-design.md`).

## Current lab: 4 — Distributed caching

**Participant 1 does lab 4 alone** (agreed by both participants), including `Results/`, which Participant 2 owned in
labs 1–3; Participant 2 reviews the PR. Task list (Ukrainian, ids П1-N):
[`docs/lab4/participant-1.md`](../lab4/participant-1.md). Branch `lab4/caching` → PR into `main`; ADRs from 0041.

| Task | Status |
|---|---|
| П1-1 Choice of the cached endpoint (2.1) | ✅ README «Лабораторна 4 → Вибір об'єкта кешування», ADR 0041 (only `GET /results`) |
| П1-2 Key schema and TTL (2.4) | ✅ ADR 0041 accepted: `polling:results:v1:{pollId}:g{gen}` + counter `polling:results:gen:{pollId}`, TTL by status (active / draft 10 s, closed 1 h) + 0–20 % jitter |
| П1-3 Cache-Aside with generations and TTL by status | ✅ `ResultsCache` (Lua lookup / invalidate), README «Cache-Aside…», «Інвалідація»; `scripts/cache-race-check.py`: lab 2 `DEL` 2–5 stale rounds of 60 in each of 5 runs → generations 0 of 60 × 5; smoke, `concurrency-checks`, `cross-instance` 8/8, `redis-outage-check` green |
| П1-4 `X-Cache` + logging | ⏳ |
| П1-5 Fallback to the DB when Redis is down (replaces ADR 0027) | ⏳ |
| П1-6 `cache-demo.py`, `cache-latency.py` | ⏳ |
| П1-7 Verification on a cold start | ⏳ |
| П1-8 README / contracts / runbook | ⏳ — **remind about cache-stampede protection first** (deferred on 2026-11-02) |
| П1-9 Defense guide, lecturer page, theory | ⏳ |

## Lab 3 — Horizontal scaling (✅ defended)

Task lists (Ukrainian, task ids П1-N / П2-N / С-N): [`docs/lab3/participant-1.md`](../lab3/participant-1.md),
[`docs/lab3/participant-2.md`](../lab3/participant-2.md). Load balancer: HAProxy (ADR 0031). All task branches are
merged: `lab3/p1-lb` (PR #7), `lab3/p1-platform` (PR #8), `lab3/p2-experiments` (PR #6, #10, #11); ADRs 0031–0034
(Participant 1), 0036–0037 (Participant 2). Defense material: guide [`docs/lab3-guide.md`](../lab3-guide.md), lecturer
page [`docs/about/lab3.md`](../about/lab3.md), README «Підсумок лаби 3».

To avoid merge conflicts, each participant edits **only their own table** below.

### Participant 1

| Task | Status |
|---|---|
| П1-1 HAProxy as the single entry point, backends without ports, `backend-3` in profile `scale` | ✅ merged via PR #7 (`f0566d4`); ADR 0031; verified on a cold start (rotation, :8082 refused, `backend-3` joins without `lb` restart, smoke 11/11 via :8080, live reload `kill -s USR2 lb` with 0 errors) |
| П1-2 Three instances + connection budget for 4+ | ✅ merged via PR #7 (`a6e298c`); ADR 0032 (4+ → `DB_MAX_POOL_SIZE = floor(90 / N)`, `max_connections` stays 100); 5 simultaneous cold starts of three instances clean; 150 threads via lb → peak 90 connections (30 × 3), psql connects. Re-check `pg_stat_activity` ≤ 90 during Participant 2's П2-5 runs |
| П1-3 Active/passive health checks, node exclusion (read path) | ✅ merged via PR #8; ADR 0033; `scripts/lb-failover.py`: stop × 2, kill × 2 under a GET stream → 0 non-2xx, node out in 0.3–0.5 s (passive layer4), back ~6–8 s after `start`; DB down → whole pool out in ~4.6 s (HAProxy 503 text/html), back in ~2.3 s. **To settle with Participant 2 (П2-4):** no `observe layer7`, no 5xx retries; vote backend can `track be_api/backend-N` |
| П1-4 Algorithms + live switch + distribution | ✅ merged via PR #8; ADR 0034; `scripts/lb-algorithm.sh` (validate + SIGUSR2), `scripts/lb-distribution.py`; RR 50/50, LC 53/47, weighted 75/25, source 0/100 (and 3-instance table); RR → LC → RR under `load.py` mixed: 0 5xx |
| П1-5 Lab 2 chain through the balancer | ✅ merged via PR #8; `cross-instance.sh` / `.http` default to :8080 (8/8, steps split 4/4), `docker-compose.debug.yml` (127.0.0.1:8091–8093) for direct access; `polls.http` already on :8080 |
| П1-6 Architecture diagram, deployment docs, SPOF | ✅ merged via PR #8; README lab 3 subsections (diagram, deployment, SPOF with Keepalived/VRRP diagram), RACI, repo structure; runbook «Load balancer (lab 3)», contracts |
| П1-7 Close-out | ✅ cold start: smoke 11/11 via :8080, `cross-instance.sh` 8/8, distribution 150/150, kill demo 0 errors; log, ADR index |

### Participant 2

| Task | Status |
|---|---|
| П2-1 Artificial delay on one instance | ✅ merged (PR #6): `Common/Diagnostics/ArtificialDelay.cs`, ADR 0036; 200 ms on `backend-2` → ~215 ms there, `/health` not delayed; off by default |
| П2-2 Load generator | ✅ merged (PR #6): `scripts/load.py`; one process tops out at ≈ 1.8k rps (`read`) — run several in parallel |
| П2-3 RR vs Least Connections with a slow node | ✅ merged (PR #10): RR 50/50, ≈ 300 rps, p95 209 ms; LC 97.5/2.5, ≈ 1.7–2.0k rps, p95 23–28 ms; p99 ≈ 215 ms in both (2.5 % still on the slow node); README |
| П2-4 Node loss during voting | ✅ merged (PR #10): `be_vote` in `haproxy.cfg` (ADR 0037) — own checks instead of `track`; `kill-test.py` via the LB: 6 kill + 1 stop runs after a cold start, 0 client errors, DOWN in ≈ 1 s (before: 6 × 502 with П1-3, 52 errors with П1-1); 503 trap verified with `redis-outage-check.py` |
| П2-5 Scale-out 1 / 2 / 3 | ✅ merged (PR #10): no CPU limits → flat (one backend served ≈ 5k reads/s); with `cpus: 1` per backend read 1491 / 2785 / 3218 rps, write 108 / 153 / 242 → plateau ≈ 250–300; DB connections 77–79 of 90 on 3 instances (П1-2 criterion) |
| П2-6 Next bottleneck | ✅ merged (PR #10): row locks on the hot `vote_count` rows (`Lock` = 26–29 of ≈ 30 active sessions); next — the connection budget for 4+ instances; README |
| П2-7 Lab 2 scripts via the LB, docs | ✅ merged (PR #10): `kill-test`, `concurrency-checks`, `redis-outage-check` default to the LB; `results-cache-demo` → `docker-compose.debug.yml`; runbook, contracts, ADR 0037 |

### Joint (lab 3)

| Task | Status |
|---|---|
| С-1 Confirm the agreements and HAProxy | ✅ followed by both in practice (HAProxy, branches, file ownership, ADR ranges) |
| С-2 PR reviews | ✅ PR #7, #8, #10, #11 merged |
| С-3 README consolidation | ✅ Participant 2, PR #11: README «Підсумок лаби 3» (one algorithm table, one node-failure table, §3 checklist) |
| С-4 Defense rehearsal | ✅ guide + dry run (Participant 2, PR #11), joint rehearsal done, lab defended |
| С-5 `labs/lab3-summary.md` | ✅ written 2026-11-02 |

### Lab 2 (✅ defended)

All П1/П2 tasks of lab 2 are merged (PR #2, #4, #3) and were verified on 2026-10-27; С-1…С-4 done.
- С-6 ✅ `labs/lab2-summary.md` + defense guide `docs/lab2-guide.md` — merged via PR #9 (2026-10-28); lecturer page
  `docs/about/lab2.md` added by Participant 2 (PR #11).
- С-5 ✅ dry run 2026-10-28, joint rehearsal done, lab defended.

## All labs

| Lab | Status |
|---|---|
| 1 System Design + MVP | ✅ defended (per Participant 1, 2026-10-28); `labs/lab1-summary.md` was never written |
| 2 Stateless | ✅ defended; `labs/lab2-summary.md`, `docs/lab2-guide.md`, `docs/about/lab2.md` |
| 3 Horizontal Scaling | ✅ defended; `labs/lab3-summary.md`, `docs/lab3-guide.md`, `docs/about/lab3.md` |
| 4 Distributed Caching | 🟡 in progress (Participant 1 alone), branch `lab4/caching`: П1-1 … П1-3 done |
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
- Lab 3 merged into `main`: PR #6 (П2-1, П2-2), PR #7 `lab3/p1-lb` (П1-1, П1-2), PR #8 `lab3/p1-platform`
  (П1-3 … П1-7, `d4bad11`), PR #10 (П2-3 … П2-7, `e2a9b38`), PR #11 (С-3, С-4: README summary, `docs/lab3-guide.md`,
  lecturer pages, `d567b02`). PR #9 `lab2/defense-guide` (lab 2 С-6, `9f7b2d9`). `1c03d0d` renamed `docs/defense/`
  → `docs/about/`. Open PRs: none (2026-11-02).
- `.gitattributes` keeps LF in the repository. If Git shows whole-file changes after a pull, run
  `git add --renormalize .` and check that `git diff --cached` is empty — then nothing really changed.

## Next steps

- **Lab 4 (Participant 1):** next П1-4 (`X-Cache` + logs), then П1-5 (fallback to the DB, replaces ADR 0027). Cache-stampede protection is deliberately out of scope
  for now — remind Participant 1 before П1-8 and when preparing the defense (П1-9).
- Record what the lecturer asked at the lab 2 / 3 defenses in `labs/lab2-summary.md` / `lab3-summary.md` if remembered.
