# 0064. Lab 8: the comparison matrix comes from one series with three repeats
**Status:** Accepted · **Date:** 2026-11-17 · **Author:** Participant 1 · Corrects the single-run conclusions of 0060, 0061

## Context
Stages 2–5 were measured with single runs at different times. The DB load counts were stable, but RPS and p95 of
single runs disagreed with each other by 30–50 % (e.g. single-flight 2302 RPS vs no protection 3202 on the real
aggregate, Lock 3520 vs single-flight 2467 with the 50 ms delay) — too noisy for the 2.7 matrix.

## Decision
- `load-tests/series-lab8.sh` (≈ 30 min): one fresh stack on the lab 8 overlay, repeats interleaved (repeat 1 of every
  mode, then repeat 2…) so machine drift spreads over the modes:
  - stampede sustained 30 s, 500 VUs, invalidation every 200 ms: None / SingleFlight / Lock × delay 50 ms and the real
    aggregate × 3;
  - stampede burst, delay 50 ms × 1 (the DB count is deterministic);
  - penetration, 100 missing ids: None without negative caching (fully unprotected "before"), Lock without it, Lock
    with it × 3;
  - control: lab 5 scenario A at 50 / 200 VUs with the pre-lab-8 behaviour (SingleFlight, no negative caching) and
    the lab 8 defaults × 2.
- `stampede.sh` / `penetration.sh` take `REP` and append a row to `results/*-summary.tsv`;
  `series-lab8-report.py` prints the matrix as median [min–max].
- The matrix in README «2.7» uses only these numbers; the single-run tables of 2.2 / 2.4 stay as the first look, with a
  note.

## Consequences
Measured 2026-11-17, 0 % errors in every run (median [min–max] of 3):

| Run | Mode | DB loads per invalidation | RPS | p95 | p99 |
|---|---|---|---|---|---|
| sustained, delay 50 | None | 123.7 [121.1–131.9] | 1075 [917–1312] | 1485 ms | 1662 ms |
| sustained, delay 50 | SingleFlight | 2.2 | 3765 [3742–3868] | 294 ms | 387 ms |
| sustained, delay 50 | Lock | 1.0 | 3420 [3276–3467] | 257 ms | 397 ms |
| sustained, real | None | 79.5 [76.6–97.2] | 2487 [2302–2513] | 706 ms | 1139 ms |
| sustained, real | SingleFlight | 2.0 | 3791 [3744–3837] | 290 ms | 404 ms |
| sustained, real | Lock | 1.0 | 3740 [3672–3908] | 289 ms | 393 ms |
| burst, delay 50 (× 1) | None / SingleFlight / Lock | 485.8 / 2.2 / 1.0 | — | 1207 / 272 / 322 ms | — |

Penetration (100 missing ids): no protection at all 100 % of requests reach the DB, 953 RPS, p95 515 ms; Lock
without negative caching 56.0 %, 1259 RPS, p95 288 ms; with it 0.15 %, 3217 RPS, p95 137 ms.
Scenario A control: 50 VUs 1357 → 1267 RPS (−7 %), p95 87 → 95 ms; 200 VUs 1763 → 1804 RPS, p95 568 → 562 ms.

Corrections to the single-run conclusions:
- **On the real aggregate protection does help** under a stream of invalidations: +50 % RPS, p95 ×2.4 lower (0060
  said "no throughput gain"; the 28 % drop was noise).
- **Lock is not faster than single-flight**: on two instances 1 vs 2 loads per invalidation is invisible to the
  database, the lock wait costs Redis round-trips — −9 % RPS, −13 % p95 (0061's "3520 vs 2467" was noise). Its gain
  is the bound "1 load, not N" as the number of instances grows, and it is what the assignment asks to prove.
- The lab 8 defaults cost ≈ 7 % of throughput at 50 VUs in ordinary reads (scenario A) and nothing at 200 VUs.
- Single repeats and the closed model (coordinated omission) remain limits; differences below ~10 % are not claimed.
