# 0060. Lab 8: stampede protection switch, DB-side load count, simulated expensive aggregate
**Status:** Accepted, single-run numbers corrected by 0064 · **Date:** 2026-11-17 · **Author:** Participant 1

## Context
Lab 8 asks to reproduce Cache Stampede / Thundering Herd on an expensive cached read with 500+ VUs, to show the mass of
database calls and then to prove that protection brings them down to 1. Since lab 4 we already have the cached object
(`GET /api/polls/{id}/results`, Cache-Aside with generations, ADR 0041) and single-flight per instance (ADR 0044), but:
- there was no way to turn the protection off, so no "before" to compare with;
- lab 4 counted DB loads on the client (distinct `generatedAt`), which is indirect;
- our aggregate is cheap: it is read from the denormalized `options.vote_count` in 1–2 ms, so the miss window is short.
  First measurement without protection, 500 simultaneous readers: 142 DB loads per invalidation on the first run after a
  cold start (cold pools, JIT), but only 21 on a warm stack — not a reliable live demo, and with a warm stack
  protection did not even improve throughput, because the bottleneck was the backends' CPU, not the database.

## Decision
- **Switch `ResultsCache:StampedeProtection`** (env `RESULTS_STAMPEDE_PROTECTION`): `None` — every miss reads the
  Primary and writes the cache itself; `SingleFlight` (default) — lab 4 behaviour. Both paths share one method,
  `ResultsService.LoadAndCacheAsync` (Primary read, cache write only for Primary data). Changing it needs a backend
  restart, like `RESULTS_CACHE_ENABLED` (ADR 0046).
- **DB loads are counted by PostgreSQL itself**: `pg_stat_statements` (`shared_preload_libraries` on the Primary of
  both shards in compose; the extension is created by the migration `EnablePgStatStatements`, so no manual step). The
  aggregate query carries an EF tag `results-load` (an SQL comment), and `calls` of that statement after
  `pg_stat_statements_reset()` is the number of times the aggregate was read from the database.
- **Simulated expensive aggregate**: `Diagnostics:ResultsLoadDelayMs` (env `RESULTS_LOAD_DELAY_MS`, default 0) adds
  `SELECT pg_sleep(…)` before the aggregate query on the same context, so every DB read of the aggregate holds a
  connection that long — the way a heavy aggregate (e.g. a COUNT over a viral poll's votes) would. Same idea as the
  lab 3 slow node (ADR 0036): off by default, stated openly at the defense; reports show both the real aggregate and
  the simulated one. It is also what stage 3 needs to test a load that outlives a lock lease.
- **Experiment** — `load-tests/scenario-stampede.js` + `load-tests/stampede.sh <None|SingleFlight> [burst|sustained]`
  on `load-tests/docker-compose.loadtest-lab8.yml` (8 threads: one core per backend and per shard Primary, k6 on 6–7).
  The invalidation is what a vote does — `INCR` of the generation, by k6 itself through `k6/experimental/redis`.
  `burst` (live demo): 500 VUs wait for a common moment, the key is invalidated 50 ms before it, all read at once;
  5 rounds, 3 s apart, round 0 without invalidation (connections). `sustained` (matrix): 500 VUs read without pauses,
  invalidation every 200 ms. Warm-up loads (setup, round 0) are counted by k6 via `X-Cache: MISS` and subtracted.

## Consequences
Measured 2026-11-17, Participant 1's machine, 2 backends, poll #1 (Shard A), 0 % errors in every run:

| Run | Protection | DB loads per invalidation | RPS | p95 | p99 |
|---|---|---|---|---|---|
| burst, real aggregate | None | 21.2 (142 on the first run after a cold start, p95 3.8 s) | — | 511 ms | 523 ms |
| burst, real aggregate | SingleFlight | 2.2 | — | 433 ms | 444 ms |
| burst, delay 50 ms | None | 433.8 of 500 readers | — | 1676 ms | 1754 ms |
| burst, delay 50 ms | SingleFlight | 2.0 | — | 564 ms | 612 ms |
| sustained 20 s, real aggregate | None | 83.7 | 3202 | 472 ms | 790 ms |
| sustained 20 s, real aggregate | SingleFlight | 2.2 | 2302 | 480 ms | 758 ms |
| sustained 30 s, delay 50 ms | None | 111.1 | 593 | 1621 ms | 2103 ms |
| sustained 30 s, delay 50 ms | SingleFlight | 2.2 | 2467 | 423 ms | 630 ms |

- With an expensive aggregate the herd is almost the whole crowd (434 of 500) and it exhausts the pools (2 × 30
  connections): throughput ×4.2 lower and p95 ×3.8 higher than with single-flight.
- With the real aggregate protection cuts DB loads ×10–40; these single runs showed no throughput gain (single-flight
  even 28 % lower). **Corrected by ADR 0064**: in a series of three repeats protection gives +50 % RPS and ×2.4 lower p95
  on the real aggregate too — the single runs were noise.
- Single-flight leaves one load per instance (2.0–2.2 on 2 instances); getting to 1 is stage 3 (distributed lock).
- `pg_stat_statements` adds a small per-statement overhead on the Primaries; negligible here, and the view is not
  queried by the application.
