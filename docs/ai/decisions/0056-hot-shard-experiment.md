# 0056. Lab 7: Hot Shard shown with `Range` on fresh polls, levelled with `Buckets`; one core per shard Primary
**Status:** Accepted · **Date:** 2026-11-10 · **Author:** Participant 2

## Context
Lab 7 (2.3) asks for a distribution baseline (rows, data share, write share per shard), a synthetic asymmetric load that
overloads one shard (latency spikes, CPU / memory of that shard) and a better strategy that levels it. The router already
has `Range`, `Modulo`, `Hash` and `Buckets` (ADR 0055).

## Decision
- **Distribution matrix:** `scripts/shard-distribution.py` — a model over ids 1..N for all four strategies (votes skewed to
  the newest 10 % of polls, like a real polling service) and `--live`: polls + votes generated through the API, write share
  counted twice — by `X-Shard` and by each shard's `pg_stat_database` tuple counters (read after 11 s: idle sessions publish
  statistics with a delay, lab 6).
- **Hot Shard source = `Range`, not `Modulo`:** sequential poll ids spread perfectly under `id % N`, so modulo has no
  realistic hot shard here; its weakness is resharding (2.5). `Range` is partitioning by creation time: with the boundary
  `SHARD_RANGE_SIZE=51` the seed (ids 1..50) is the "archive" on Shard A and every new poll lands on Shard B — and new polls
  are exactly where the votes go.
- **Load:** `load-tests/scenario-hot-shard.js` — 40 fresh polls, 80 % vote / change vote, 20 % details, 10 → 100 VUs ×
  30 s; per-shard latency and request counts from `X-Shard` (`shard_A_duration`, `shard_B_duration`).
- **Stand:** `load-tests/docker-compose.loadtest-shards.yml` — each shard Primary on one dedicated core (1 GB), replicas
  on their own cores, backends 2 cores, k6 on cores 16–23. One core makes the database saturate before the backends, so the
  imbalance shows in the shard's own CPU. `load-tests/hot-shard.sh` runs `Range` then `Buckets`, each on a fresh stack
  (ADR 0047), prints the report (`hot-shard-report.py`) and restores the default stack.
- **Optimised strategy = `Buckets`** (default since ADR 0055).

## Consequences
- Measured 2026-11-10 (24 vCPU, Docker Desktop): `Range` — 100 % of requests on Shard B, its CPU 99 %, Shard A 1–3 %,
  throughput stuck at ≈ 520 RPS from 10 VUs, p95 35 → 331 ms. `Buckets` — 47 / 53 %, both shards busy, ≈ 1000 RPS (×1.9),
  p95 at 10 / 25 / 50 VUs 23 / 56 / 127 ms instead of 35 / 85 / 177. At 100 VUs both runs reach ≈ 300 ms p95 on the hotter
  shard: closed model, twice the requests. 0 % errors in every step. Report: `docs/lab7/hot-shard.md`.
- Live matrix (`Buckets`, 100 polls / 3000 votes): writes A 55.6 / B 44.4 % by `X-Shard`, 55.1 / 44.9 % by PostgreSQL;
  data A 42 / B 58 % because the 50-poll seed put 32 polls on B (small sample). Model on 10 000 ids: `Range` data 50 / 50
  but writes 5.6 / 94.4 %, `Hash` / `Buckets` 53 / 47 %.
- A single viral poll is a hot **key**, not a hot shard: no hash spreads it. Reads are absorbed by the results cache
  (lab 4); writes would need a split counter or a composite key — not implemented, documented as the method's limit.
- Direct-DB scripts adapted to shards in the same stage: `kill-test.py`, `load.py`, `redis-outage-check.py`,
  `replication-check.py --shard A|B`, counter lines of `series*.sh`, `env-spec.sh`; all re-run green. `db-failure-check.py`
  only got the counter check: its "both nodes down → /health 503" step no longer holds while Shard B is alive (stage 4).
