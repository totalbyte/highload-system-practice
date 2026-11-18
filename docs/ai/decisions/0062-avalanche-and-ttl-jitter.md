# 0062. Lab 8: Cache Avalanche experiment and symmetric TTL jitter with a switch
**Status:** Accepted · **Date:** 2026-11-17 · **Author:** Participant 1 · Amends 0041 (jitter formula)

## Context
Lab 8 asks to reproduce synchronized expiry of many keys (2.3) and to protect against it with
`TTL = Base_TTL ± Random_Jitter` (2.5). Since lab 4 the results cache had jitter `TTL × (1 + 0…0.2)` (ADR 0041) — only
upwards and with no way to turn it off, so the "before" could not be shown.

## Decision
- **Symmetric jitter with a switch**: `ResultsCache:TtlJitter` (env `RESULTS_TTL_JITTER`, default 0.2):
  `TTL = Base × (1 + U(−j, +j))`, i.e. active / draft 10 s ± 20 % (8–12 s), closed 1 h ± 20 %. `0` disables it — only
  for the avalanche demo. Clamped to [0, 0.9] so a TTL never becomes zero or negative.
- **Experiment** — `load-tests/scenario-avalanche.js` + `load-tests/avalanche.sh <jitter>` + `avalanche-report.py`:
  - stack with `SEED_POLLS=1000` (832 visible polls = keys; drafts answer 404 and are skipped) on the lab 8 overlay;
  - `avalanche.sh` recreates the backends with the jitter (and the optional `RESULTS_LOAD_DELAY_MS`, ADR 0060), empties
    the results cache, resets `pg_stat_statements`, and samples both shard Primaries every second with psql `\watch i=1
    c=N` (reads of the aggregate, active client sessions);
  - k6 `setup()` warms all keys at once (batches of 100), then 300 VUs read random polls for 60 s, no votes — keys go
    only by TTL; latency and misses per second come from per-second sub-metrics (tag `sec`).
- Protection mode stays the default `Lock` (ADR 0061): per key it already gives one load, so what remains is exactly
  the avalanche — many keys at once.

## Consequences
Measured 2026-11-17, 832 keys, 300 VUs, 60 s, 0 % errors (seconds 0–4 are the warm-up and excluded):

| Run | DB loads/s max | median | stdev | active sessions max | p95 per second max / median | p95 / p99 overall |
|---|---|---|---|---|---|---|
| aggregate + 50 ms, jitter 0 | 269 | 6 | 86 | 26 | 553 / 269 ms | 278 / 459 ms |
| aggregate + 50 ms, jitter ±20 % | 162 | 58 | 43 | 17 | 603 / 222 ms | 252 / 397 ms |
| real aggregate, jitter 0 | 325 | 11 | 85 | 1 | 585 / 201 ms | 231 / 334 ms |
| real aggregate, jitter ±20 % | 178 | 53 | 46 | 1 | 516 / 224 ms | 251 / 394 ms |

- Without jitter the keys stay synchronized: a wave every ~10 s (≈ 830 loads over 4–5 s, up to 269/s and 26 active
  sessions, p95 up to ≈ 550 ms) and 5 s of zero DB load between waves. With ±20 % the first wave is still there (all keys
  were written in the same second, ±20 % of 10 s spreads them over only 4 s), but each cycle re-draws the TTL and by
  the third cycle the load is a flat 30–120 loads/s.
- Latency follows the misses (k6 counts a miss by the request's start second, the DB curve lags by ≈ 1 s): seconds
  with ≥ 200 misses have p95 370 ms and 2169 RPS against 245 ms and 2781 RPS in quiet seconds (delay 50, jitter 0);
  with ±20 % there are 5 such seconds instead of 12.
- The p95-per-second maximum is not a good signal here: both runs have one unrelated ~1 s stall (sec 3 / 14–15, fewer
  requests and p95 ≈ 1.2 s / 0.6 s in both); the medians and the DB curves are.
- On the real 1–2 ms aggregate the avalanche is visible only in the DB load (325 loads/s peak), not in sessions or
  latency — the database absorbs it. Jitter is cheap insurance, it matters when the recompute is expensive.
- Jitter does not help when the keys disappear together for another reason (Redis restart, flush): that is a cold
  cache, the first wave again; per-key protection (Lock) keeps it at one load per key.
