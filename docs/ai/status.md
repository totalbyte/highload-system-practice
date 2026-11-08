# Project status

> Snapshot of the current state. **Rewrite outdated lines in place** — history belongs in `log/`.
> Last updated: 2026-11-08 by Participant 1 (lab 6 stages 1–5 — see `log/2026-11-08-p1-lab6-topology.md`).

## Current lab: 6 — Database replication

**Participant 1 does lab 6 alone** (agreed by both participants). Branch `lab6/replication`, ADRs from 0049. Plan by
stages: [`docs/lab6/plan.md`](../lab6/plan.md). Measurements (stage 5) run on Participant 1's machine (8 threads), so a
single-primary baseline is measured again in the same series; lab 5's absolute numbers (Participant 2's 24 vCPU machine)
are not comparable.

| Stage | Status |
|---|---|
| 1. Topology (2.1) | ✅ `postgres` (Primary) + `postgres-replica`, async streaming, `pg_basebackup` on an empty volume, slot `replica_1` (ADR 0049); `scripts/replication-check.py`; verified on a cold start (17 s), smoke, Primary restart, replica outage, `concurrency-checks`. Committed `7ea6f27` |
| 2. Read/Write Separation, classification (2.2, 2.3) | ✅ `ReadDb.Eventual` for catalog and details, everything else on the Primary, results MISS stays on the Primary, `X-DB-Node`, `READ_REPLICA_ENABLED` (ADR 0050); `scripts/rw-routing-check.py`; all regressions green. Committed `f19a6bf` |
| 3. Stale Read, Read-After-Write (2.3, 2.4) | ✅ Session Sticky in Redis, TTL 5 s, set before the response (ADR 0051); `scripts/stale-read-demo.py`; MISS on the replica measured: 6–11 stale rounds of 60 without artificial lag, 0 on the Primary. Committed `31d3353` |
| 4. Failure scenarios (2.5) | ✅ `DbNodeMonitor`, Primary Fallback, 503 `Read-Only Mode`, `/health` 503 only when both are down (ADR 0052); `scripts/db-failure-check.py`: 0 reader errors in both failures, writes refused in milliseconds; no false failover under `load.py`. Committed `3e68213` |
| 5. Single Primary vs Primary + Replica (2.6) | ✅ `docs/lab6/load-comparison.md`, ADR 0053, 17 runs on 8 threads, 0 % errors: no throughput gain, read p95 about half under writes up to saturation, writes −25 % at 10 VU; lag up to 29.5 s above saturation, TTL stays 5 s. Participant 1 commits |
| 6. README, guide, lecturer page (§3, §4) | ⏳ next |

## Web UI (outside the labs, merged via PR #15)

React + Vite + TS in `frontend/`, container `web` (nginx) behind HAProxy on :8080 — ADR 0048. Pages: list with tabs
(active / closed / all) and live counters, poll page (vote / change vote, results refreshed every 5 s, node and
`X-Cache` badge, author actions publish / close / delete), create form, login / register, my polls, favorites
(localStorage). New endpoint `GET /api/polls/{id}/vote`.

## Lab 5 — Load testing & performance baseline (✅ defended)

Both participants' tasks were done in one branch `lab5/load-tests`, merged via PR #14. Plan by stages with who explains
what at the defense: [`docs/lab5/plan.md`](../lab5/plan.md); ADRs 0045–0047.

| Stage | Status |
|---|---|
| 1. Load-test environment | ✅ k6 1.3.0 in Docker inside `app-network`, every component pinned to its own cores with limits, k6 on cores 16–23 (ADR 0045); `env-spec.sh`; `RESULTS_CACHE_ENABLED=false` → `X-Cache: DISABLED` (ADR 0046) |
| 2. Scenarios A / B / C | ✅ `load-tests/scenario-*.js`: warm-up 20 s → 10 / 25 / 50 / 100 / 200 VUs × 40 s; B users partitioned per VU (no artificial 409) |
| 3. Runs, tables, saturation point | ✅ `series.sh` (fresh stack per run, ADR 0047 — the first series drifted), `run.sh` (CPU + PG sessions / tx per 5 s), `report.py`; A ≈ 50 VUs / 3.7k RPS, B ≈ 10 VUs / 470 RPS then falling, C ≈ 400 VUs / 1.6k RPS; 0 % errors everywhere |
| 4. Scaling, cache | ✅ read E(2) 0.86, E(3) 0.72; write 365 → 276 → 229 RPS (negative); cache off: PG tx/s +55 %, RPS −28 % |
| 5. Bottleneck, baseline, docs | ✅ primary bottleneck: row-lock contention on hot `options.vote_count`; README «Лабораторна 5» (tables, Mermaid charts, baseline card), `docs/lab5-guide.md`, `docs/about/lab5.md`, open model (coordinated omission) |

Copilot review of PR #14: 5 load-script issues fixed (user overlap in B open model / C at 800 VUs, fail-fast `series.sh`, smoke `checks` threshold; C-extended and open model re-measured). `labs/lab5-summary.md` was never written.

## Lab 4 — Distributed caching (✅ defended, merged via PR #13)

**Participant 1 does lab 4 alone** (agreed by both participants), including `Results/`, which Participant 2 owned in
labs 1–3; Participant 2 reviews the PR. Task list (Ukrainian, ids П1-N):
[`docs/lab4/participant-1.md`](../lab4/participant-1.md). Branch `lab4/caching` → PR into `main`; ADRs from 0041.

| Task | Status |
|---|---|
| П1-1 Choice of the cached endpoint (2.1) | ✅ README «Лабораторна 4 → Вибір об'єкта кешування», ADR 0041 (only `GET /results`) |
| П1-2 Key schema and TTL (2.4) | ✅ ADR 0041 accepted: `polling:results:v1:{pollId}:g{gen}` + counter `polling:results:gen:{pollId}`, TTL by status (active / draft 10 s, closed 1 h) + 0–20 % jitter |
| П1-3 Cache-Aside with generations and TTL by status | ✅ `ResultsCache` (Lua lookup / invalidate), README «Cache-Aside…», «Інвалідація»; `scripts/cache-race-check.py`: lab 2 `DEL` 2–5 stale rounds of 60 in each of 5 runs → generations 0 of 60 × 5; smoke, `concurrency-checks`, `cross-instance` 8/8, `redis-outage-check` green |
| П1-4 `X-Cache` + logging | ✅ ADR 0042: header `HIT` / `MISS`, `{HIT}` in the HAProxy log, Debug logs via `CACHE_LOG_LEVEL`; smoke 25/25 |
| П1-5 Fallback to the DB when Redis is down (replaces ADR 0027) | ✅ ADR 0043: `X-Cache: BYPASS` 200 in 68 ms (was 503 after 5.2 s), fail-fast client, Redis `--save ""` (it reloaded `dump.rdb` on `start` — stale HIT in a counter-test); `redis-outage-check.py` rewritten, ALL PASSED |
| П1-6 `cache-demo.py`, `cache-latency.py` | ✅ demo of the 3 procedure items (with Redis gen / TTL per read); cold vs hot on poll #1, 3 × 500 pairs: MISS p50 ≈ 3.8 ms, HIT p50 ≈ 2.0 ms (× 1.9); README «Cold vs Hot» |
| П1-7 Verification on a cold start | ✅ @ `d20999a`: healthy in 23 s; smoke 25/25, `cross-instance.sh` 8/8, `concurrency-checks`, `cache-demo` (rc 0), `cache-latency` (MISS 3.83 / HIT 1.99 ms p50), `cache-race-check` 0 of 60, `redis-outage-check`, `kill-test` (800 votes, 0 errors), `lb-failover --kill` (0 of 17 911), `results-cache-demo` no / no |
| П1-10 Cache-stampede protection (decided before П1-8) | ✅ ADR 0044: single-flight per instance (`ResultsSingleFlight`); `cache-stampede-check.py`: 6.7–14.4 → 2.1–2.4 DB loads per invalidation (2 instances, 100 readers); race check 0 of 60, all regressions green |
| Re-verification from scratch (after П1-10) | ✅ cold start 22 s; 10/10 checks; load: cache on 2730 read rps / 0 DB loads, mixed 47 % HIT with 209 DB loads/s for 116 votes/s, Redis down 1355 rps (p95 ×2.4), 0 errors; single-flight 3.1 loads on 3 instances |
| П1-8 README / contracts / runbook | ✅ README «Архітектура з шаром кешу» (flowchart + sequence diagram, both render), «Підсумок лаби 4» (requirement → evidence, load table, from-scratch check, defense commands), RACI, stack; root `CLAUDE.md` fixed (HAProxy, no :8082, lab 4 rule and task list) |
| П1-9 Defense guide, lecturer page, theory | ✅ `docs/lab4-guide.md`, `docs/about/lab4.md`; dry run from a cold start ≈ 75 s, two script fixes (wait for Redis reconnect); `labs/lab4-summary.md` was never written |

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
| 4 Distributed Caching | ✅ defended (per Participant 1, 2026-11-08); `docs/lab4-guide.md`, `docs/about/lab4.md`; `labs/lab4-summary.md` was never written |
| 5 Load Testing | ✅ defended (per Participant 1, 2026-11-08); `docs/lab5-guide.md`, `docs/about/lab5.md`; `labs/lab5-summary.md` was never written |
| 6 Database Replication | 🟡 in progress (Participant 1 alone), branch `lab6/replication`: stages 1–5 of 6 done |

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

- **Lab 6 (Participant 1):** stage 6 — README «Лабораторна 6» with the architecture diagram, `docs/lab6-guide.md`, `docs/about/lab6.md`, rehearsal, see
  [`docs/lab6/plan.md`](../lab6/plan.md).
- Known bug outside lab 6: `POST /api/polls` with a valid token and no `options` answers 500 instead of 422 (NullReferenceException in
  `PollValidators.cs:17`, in the code since lab 1). Not fixed.
- Record what the lecturer asked at the lab 2–5 defenses in the lab summaries if remembered.
