# 0053. Lab 6: how Single Primary and Primary + Replica are compared; sticky TTL stays 5 s
**Status:** Accepted · **Date:** 2026-11-08 · **Author:** Participant 1

## Context
Lab 6 (2.6) compares the two topologies with the lab 5 scripts. Lab 5 was measured by Participant 2 on a 24 vCPU machine; lab 6 runs on Participant 1's laptop with 8 threads, where
the cpusets of ADR 0045 do not exist. Results: [`docs/lab6/load-comparison.md`](../../lab6/load-comparison.md).

## Decision
- **`load-tests/docker-compose.loadtest-8cpu.yml`:** one thread per measured component, the Primary and the Replica get the same resources, k6 on threads 6–7 (it used ≈ 50 % of one thread in the pilot).
  `run.sh` takes `OVERLAY`. Lab 5's numbers are not compared; a new baseline is measured in the same series.
- **Single Primary is a real single node:** `READ_REPLICA_ENABLED=false`, replica container stopped, **slot dropped**. A stopped replica's slot pins WAL: segments are created instead of recycled, and scenario B
  measured 120 instead of 198 RPS at 200 VU. The first series was wrong because of it, see Consequences.
- **A new mixed run (`mixed` in `series-lab6.sh`):** scenario A under 15 VUs of scenario B. A read-only workload cannot show the replica's effect: reads just move to a node of the same size. Isolation of reads
  from writes is visible only when both happen together.
- **Stand checks:** before each run the script waits for real answers from both instances (HAProxy shows `UP` right after DNS resolution, before the first check, a race that stopped the first series) and verifies
  `X-DB-Node` against the expected topology. Any failure stops the series. `load-tests/series.sh` of lab 5 has the same race and was left as it is.
- **Sticky TTL stays 5 s, no lag-aware routing** (decided by Participant 1). Lag above the TTL appeared only above the saturation point, in 2 of 4 mixed runs. Critical reads go to the Primary regardless. A longer TTL would
  not cover 29 s and would take more reads off the replica; routing by lag is more code than the lab asks for and would change the stale read demo. It is the first step if lag matters in production.

## Consequences
- Result: one replica of the same size adds **no throughput** (A: within the spread). Mixed load up to the saturation point: read p95 about half (≈ 75 vs ≈ 146 ms at 50 VU), writes ≈ +40 %, write p99 2.5 times lower.
  Write cost: −25 % RPS at 10 VU, −4 % at 200 VU. Scenario C: Session Sticky sends nearly all reads to the Primary, so no effect. 0 % errors in all 17 runs, no node state changes, counters consistent.
- **The artefact** is recorded in the report because it changed the conclusion: with the stale slot the mixed run showed reads +40 % RPS and writes 2.1 times. It was found only because scenario B contradicted expectations.
- Lag: max 206 ms up to saturation, up to 29.5 s above it, wide spread between identical runs. **Cause not established**: 0 recovery conflicts in the two diagnostic runs, which did not reproduce the jump either. Conflicts were not counted in the runs that jumped.
- Limits of the measurement: sibling threads share physical cores, shared disk, 1–3 runs per configuration, wide spread for Single in the mixed run. Only large differences are conclusions. The sampler takes ≈ 10 s per round, so short lag spikes may be missed.
