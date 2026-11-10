# 0059. Lab 7: Single Node vs two shards measured per query type (shard-local write, shard-local read, fan-out)
**Status:** Accepted · **Date:** 2026-11-10 · **Author:** Participant 2

## Context
Lab 7 (2.6) asks to compare a single database node with the sharded topology using the lab 5 scripts, for shard-local and
cross-shard fan-out queries: RPS, p95 / p99, error rate, saturation point. The lab 5 scenarios mix query types (scenario A
has 15 % catalog), which would blur the one thing the comparison is about.

## Decision
- **One k6 script, three pure modes:** `load-tests/scenario-shards.js` with `MODE=write` (vote / change vote into 40 fresh
  polls), `read` (details of those polls — replica reads) and `catalog` (`GET /api/polls?status=active&pageSize=20`),
  the lab 5 stepped profile (`lib.js`) at 10 → 200 VUs × 30 s.
- **Single Node = `SHARD_COUNT=1`** on the same stack and limits (Shard A Primary + Replica; Shard B containers idle). Same
  code path, only the router differs.
- **Stand:** `docker-compose.loadtest-shards.yml` (one core per database node, ADR 0056), fresh stack per run (ADR 0047),
  `load-tests/series-lab7.sh` runs the six runs; `load-tests/shards-report.py` builds the tables, CPU per database node and
  backend, saturation point (last step after which RPS grows < 10 %) and Mermaid charts.

## Consequences
- Measured 2026-11-10 on 24 vCPU, 0 % errors everywhere: write ≈ 420 → ≈ 780 RPS (×1.9, Single's Primary at 98–99 % from
  25 VUs, both Primaries 96–100 % sharded); read ≈ 1400 → ≈ 2700 RPS (×1.9, replicas saturated); catalog ≈ 390 → ≈ 420 RPS
  (×1.1) with both replicas at 91–102 % — every fan-out request does its work on every shard; at 200 VUs the fan-out
  p95 / p99 is worse (853 / 929 vs 665 / 750 ms), the slowest shard sets the tail.
- Saturation: write 10 VU / 420 RPS → 25 VU / 772 RPS; read 10 / 1445 → 25 / 2675; catalog 10 / 455 → 10 / 410.
- Not comparable with the lab 5 / 6 absolute numbers (database nodes limited to one core here).
- Catalog optimisations (cache of the first page, a catalog index on one node, cursor pagination) are noted, not built.
- `series-lab7.sh` aborted at the report on the first run (an f-string with nested quotes, Python < 3.12) before restoring
  the default stack; fixed. Report: `docs/lab7/load-comparison.md`.
