# 0057. Lab 7: partial catalog when a shard is down, fail fast on a dead shard; cross-shard writes avoided by the aggregate, Saga on paper
**Status:** Accepted · **Date:** 2026-11-10 · **Author:** Participant 2

## Context
Lab 7 (2.4) asks for a fan-out query with its overhead compared to a shard-local one, and for a cross-shard write with an
explanation of why local ACID does not cover it (2PC, Saga or a shard-local aggregate). The catalog is the only fan-out
read (ADR 0055). Before this stage a fully stopped shard made the whole catalog fail, and every read of that shard waited
3–9 s for Docker DNS before its 503.

## Decision
- **Partial catalog:** `PollService.ListAsync` catches "node unavailable" per shard (`ReadDb.IsUnavailable`) and skips that
  shard; the controller sets `X-Shard-Unavailable: B`. All shards down → 503 `Shard Unavailable`. The catalog is an
  eventual read already (ADR 0050), so a list without one shard is acceptable and better than a 503 for everybody.
- **Fail fast on a dead shard:** `ReadDb` throws `ShardUnavailableException` (503, title `Shard Unavailable`, not logged as
  an error) when the shard's monitor sees neither node alive, instead of trying to connect.
- **`db-failure-check.py` step 3** stops both nodes of Shard A while Shard B is alive: `/health` 200 Degraded, catalog 200
  with `X-Shard-Unavailable: A`, a Shard A poll 503 in milliseconds; with `SHARD_COUNT=1` it keeps the lab 6 expectation
  (`/health` 503). The script and `cross-shard-check.py` wait until **both** backends' monitors see the failure.
- **Fan-out overhead measured with `scripts/cross-shard-check.py`:** client-side latency and PostgreSQL transaction deltas on
  all four nodes; no assertion on idle latency (parallel fan-out is within noise), the assertion is on database work.
- **Cross-shard writes:** none in the API. Voting stays shard-local by the key choice (ADR 0054); poll creation spans Shard A
  (non-transactional sequence) and the poll's shard without needing atomicity. No 2PC (`max_prepared_transactions` stays 0:
  blocking coordinator, in-doubt transactions). Account deletion is documented as a forward-only Saga, not implemented.

## Consequences
- Measured 2026-11-10, idle stack, 300 sequential requests: details p50 4.1 (A) / 2.9 (B) ms, catalog page 1 4.0 ms,
  page 10 4.5 ms; database work 2.8 transactions per details request on one node vs 8.8 per catalog request on two.
- Shard B stopped: `/health` 200 Degraded, catalog 200 in 16 ms with `totalCount` 269 → 130, Shard A poll and vote fine,
  Shard B poll 503 in 6 ms; back without a backend restart. Before the fail-fast: catalog 6 s, Shard B poll 5–9 s.
- `db-failure-check.py`, `cross-shard-check.py`, `shard-routing-check.py`, `concurrency-checks.py` pass.
- A client must treat a catalog with `X-Shard-Unavailable` as incomplete (`totalCount` counts only answering shards).
- Report: `docs/lab7/cross-shard.md`.
