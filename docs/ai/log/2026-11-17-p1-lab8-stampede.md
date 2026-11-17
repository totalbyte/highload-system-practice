# 2026-11-17 — Participant 1 — lab 8 stages 0–6: stampede, lock, avalanche, negative caching, matrix
**Lab:** 8 · **Commits:** `5169a77` (stage 0), `96845a2` (stages 1–3), `27344dd` (stage 4), `3eccd0b` (stage 5)

## Goal
Read the lab 8 assignment (Resilience Engineering), plan it strictly by the assignment (Participant 1 does lab 8 alone,
agreed with Participant 2), then stages 1–3: the cached object, an unprotected Cache Stampede with 500+ VUs, a distributed lock down to 1 DB load.

## Done
- Stage 0: `docs/labs/Lab8 - Resilience Engineering.md` (assignment from the docx), `docs/lab8/plan.md`, knowledge map
  in `CLAUDE.md`, status. Branch `lab8/resilience` from `main` was created by Participant 1.
- Stage 1: README «Лабораторна 8 → Об'єкт» — `/results` of the hot poll, why a miss is dangerous here, and that our
  aggregate is cheap.
- Stage 2 (ADR 0060): switch `RESULTS_STAMPEDE_PROTECTION` (`None` / `SingleFlight`), shared
  `ResultsService.LoadAndCacheAsync`; `pg_stat_statements` (migration `EnablePgStatStatements`, preload in compose,
  EF tag `results-load`); `RESULTS_LOAD_DELAY_MS` (`pg_sleep` before the aggregate); `load-tests/scenario-stampede.js`
  (burst / sustained, invalidation by k6 via `k6/experimental/redis`), `load-tests/stampede.sh`,
  `load-tests/docker-compose.loadtest-lab8.yml`. README, runbook, contracts, `load-tests/README.md`, code guide.
- Stage 3 (ADR 0061): `Results/ResultsDistributedLock.cs` inside the single-flight flight, lock primitives in
  `ResultsCache` (`GetEntryAsync`, `TryLockAsync`, `ReleaseLockAsync` with an own-token Lua script), `Lock` as the
  default mode; `scripts/lock-check.py` (dead owner); README «2.4» with a sequence diagram, runbook, ADR 0044 amended.
- Stage 4 (ADR 0062): symmetric jitter with `RESULTS_TTL_JITTER`; `scenario-avalanche.js`, `avalanche.sh` (psql `\watch`
  sampler on both Primaries), `avalanche-report.py` (per-second table, Mermaid chart); README «2.3, 2.5», ADR 0041 amended.
- Stage 5 (ADR 0063): negative entry `not-found` (`SetNotFoundAsync`, `ResultsCacheLookup.NotFound`), `LoadAsync` returns
  null for a missing poll, waiters under the lock answer 404 from the entry, `PollService.CreateAsync` invalidates the new
  id; `scripts/negative-cache-check.py`, `load-tests/scenario-penetration.js` + `penetration.sh`; README «2.6».
- Stage 6 (ADR 0064): `load-tests/series-lab8.sh` + `series-lab8-report.py` (`REP` and summary TSV in the runners), README
  «2.7» matrix, `docs/lab8/resilience-profile.md` (Failure Modes, Resilience Profile labs 2–8), single-run claims corrected
  in README 2.2 / 2.4 and ADR 0060 / 0061.

## Decisions (link ADRs)
- [ADR 0060](../decisions/0060-stampede-experiment.md): protection switch, DB-side count, simulated expensive aggregate.
- [ADR 0061](../decisions/0061-distributed-lock-for-results-miss.md): Redis lock behind single-flight, lease 1 s, max wait
  2 s, no fencing token (idempotent cache write keyed by generation), `Lock` is the default.
- [ADR 0062](../decisions/0062-avalanche-and-ttl-jitter.md): TTL ± j instead of + j, switch for the demo, avalanche on 832 keys.
- [ADR 0063](../decisions/0063-negative-caching.md): negative entry in the same key, 30 s, invalidate on create, no Bloom filter.
- [ADR 0064](../decisions/0064-lab8-comparison-series.md): the matrix only from one series with 3 interleaved repeats.
- Out of scope by agreement: SWR, XFetch, Redlock, Bloom filter — theory only.

## Problems & fixes
- Single runs were noisy for RPS / p95 (30–50 %): "Lock 3520 vs single-flight 2467" and "no gain on the real
  aggregate" did not survive the three-repeat series → corrected (ADR 0064); DB load counts were stable.
- Avalanche: DB loads lag the k6 misses by ≈ 1 s (start-second tag vs sample after completion) and both runs have one
  unrelated ≈ 1 s stall → latency compared by miss-wave seconds vs quiet seconds, not by the per-second maximum.
- Real aggregate (1–2 ms) gave only 21 DB loads per invalidation on a warm stack (142 right after a cold start) and no
  throughput gain from protection → simulated expensive aggregate, off by default, both sets of numbers reported.
- The warm-up round and `setup()` added a few loads → k6 counts them by `X-Cache: MISS` and `stampede.sh` subtracts them.

## Verified (how)
- Cold start (`down -v`, lab 8 overlay): healthy in 35 s, migrations on both shards, extension present.
- Stampede runs: see the table in ADR 0060 / README (delay 50 ms burst: None 434 → SingleFlight 2.0 per invalidation).
- Default stack: runbook smoke (201 / 409 / HIT with the same `generatedAt` / closed after close / 404 / 200 after a
  Postgres restart, counters 0 on both shards), `cache-race-check` 0 of 60, `cache-stampede-check` 2.2,
  `concurrency-checks`, `redis-outage-check` ALL PASSED.
- Stage 3: `stampede.sh Lock` — 1.0 DB load per invalidation (burst real / delay 50, sustained delay 50: 3520 RPS);
  `lock-check.py` with 50 and 200 readers ALL PASSED; delay 1500 > lease → 2.0 loads, 0 errors, lease warnings in both
  logs. Default stack (`Lock`): smoke, `cache-stampede-check` 1.0 (max 1) per round, `cache-race-check` 0 of 60,
  `concurrency-checks`, `redis-outage-check` ALL PASSED, no `fail:` in backend logs.
- Stage 4: cold start with `SEED_POLLS=1000` healthy in 59 s (1000 polls, 106 079 votes over both shards); four
  avalanche runs (jitter 0 / 0.2 × delay 0 / 50), 0 % errors; numbers in ADR 0062 / README.
- Stage 5: `negative-cache-check.py` ALL PASSED; four `penetration.sh` runs (on / off × 100 ids / unique), 0 % errors.
- Stage 6: `series-lab8.sh` completed in 27 min, exit 0, 0 % errors in all 34 runs; numbers in ADR 0064 / README «2.7».

## Not done / next steps
- The README sequence diagram (2.4) is not yet rendered in a browser — check all lab 8 diagrams in stage 7.
- Stages 4–7: avalanche + jitter, negative caching, matrix / failure modes / Resilience Profile, guide and lecturer page.
