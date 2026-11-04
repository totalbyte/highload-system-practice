# 2026-11-03 — Participant 2 — lab 5: load testing and performance baseline (both participants' tasks)
**Lab:** 5 · **Commits:** `4630255`, `7159ace` and the final lab 5 commit on `lab5/load-tests` (not pushed)

## Goal
Do the whole of lab 5 (both participants' parts) in stages, committing each one.

## Done
- Stage 1: k6 1.3.0 in Docker (`load-tests/docker-compose.loadtest.yml`, profile `loadtest`), every component pinned to
  its own cores with CPU / RAM limits, k6 on 8 isolated cores, targeting `lb:8080` inside the network; `env-spec.sh`;
  `ResultsCache:Enabled` switch (`X-Cache: DISABLED`).
- Stage 2: scenarios A (read), B (write), C (workflow) with warm-up and stepped 10–200 VUs, per-step summary + JSON.
- Stage 3–4: `run.sh` (resources every 5 s), `report.py` (tables, resources per step, Mermaid charts, `--compare`),
  `series.sh` (all runs), `open-model.js` (constant arrival rate). Full series run twice (see problems).
- Stage 5: README «Лабораторна 5» (environment, scenarios, per-scenario tables and charts, mean vs tail, saturation
  points, scaling efficiency, cache on / off, open model, baseline card), `docs/lab5-guide.md`, `docs/about/lab5.md`,
  `docs/lab5/plan.md`, runbook, status, knowledge map.

## Decisions (link ADRs)
- [0045](../decisions/0045-load-test-environment.md): k6 in Docker inside the network, cpusets + limits.
- [0046](../decisions/0046-results-cache-switch.md): cache on / off switch; invalidation keeps running when off.
- [0047](../decisions/0047-fresh-stack-per-load-run.md): fresh stack before every measured run.

## Problems & fixes
- Scenario B warm-up had 0.04 % errors: two VUs voted with the same random user at once; both first votes went in
  parallel, `FOR UPDATE` had no row to lock and the second INSERT got 409 from `UNIQUE` (data consistent). Fixed the
  generator: users are partitioned per VU.
- First full series: 3 instances read *worse* than 2 (3.6–4.5k vs 9.5k RPS) with PG saturated by long-running queries.
  Cause — data drift between runs on one DB (`polls` 50 → 17 370 rows after scenario C, ≈ 833k hot-row updates).
  Fixed by a fresh stack per run (ADR 0047); first series kept in `load-tests/results/run1/` (gitignored).
- Absolute numbers of the second (morning) series are ≈ 2× lower than the first (night) one — host load outside the
  cpusets. Only runs of one series are compared; conclusions are the same in both. Stated in README.
- `pg_stat_activity` showed 0 `active` sessions under write load at single samples — sessions inside an EF
  transaction are often `idle in transaction`; added that column. `GROUP BY 1` on an aggregate in my first query.
- The safety check blocked `rm load-tests/results/*` with a relative path after `cd`; not needed (timestamped files).

## Verified (how)
Second series, fresh stack per run, 0 % errors in every step of every run, per-option counter mismatches 0. App smoke
test against the overlay stack after the series — see the commit.

## Not done / next steps
Push `lab5/load-tests` and open a PR after PR #13 (lab 4) is merged; rehearse the defense together by
`docs/lab5-guide.md`; write `docs/ai/labs/lab5-summary.md` after the defense.

## Later: Copilot review of PR #14
Five valid findings, all fixed: (1) B's 200 user slots vs up to 400 VUs in `open-model.js` — open model capped at
`SLOTS` = 200; (2) C at 800 VUs reused the 500 tokens — `USERS` / `SEED_USERS=800` for that run, `setup()` refuses to
run with fewer users than VUs; (3) `series.sh` now `set -eo pipefail`; (4) `wait_state` returns 1 on timeout;
(5) `smoke.js` thresholds `checks: rate==1`. Re-measured with `ONLY="c-extended open-300 open-1200"`: C 200 / 400 / 800
VUs → 1256 / 1572 / 1540 RPS, p95 59 / 313 / 1260 ms (same conclusion, saturation ≈ 400 VUs); open model 300 req/s →
p99 42 ms, 0 dropped; 1200 req/s → 295 req/s, 36 190 dropped (75 %), p50 533 ms; errors 0, counters consistent.

