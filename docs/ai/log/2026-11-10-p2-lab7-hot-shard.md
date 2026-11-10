# 2026-11-10 — Participant 2 — lab 7 stage 3: distribution matrix and Hot Shard
**Lab:** 7 · **Commits:** not committed (stages 1–2 are `a199260`)
## Goal
Lab 7 2.3: data distribution baseline, a Hot Shard under asymmetric load and its levelling; adapt the lab 2–6 scripts that
read the database directly to two shards.
## Done
- `scripts/shard-distribution.py`: model for all strategies on ids 1..N and `--live` matrix (rows, data share, write share
  by `X-Shard` and by `pg_stat_database`).
- `load-tests/scenario-hot-shard.js` (per-shard latency / counts), `docker-compose.loadtest-shards.yml` (one core per shard
  Primary), `hot-shard.sh` (Range then Buckets on fresh stacks), `hot-shard-report.py`; report `docs/lab7/hot-shard.md`.
- Shard-aware DB checks in `kill-test.py`, `load.py`, `redis-outage-check.py`, `replication-check.py --shard A|B`,
  `db-failure-check.py` (counters only), `series.sh`, `series-lab6.sh`, `env-spec.sh`.
## Decisions (link ADRs)
- [0056](../decisions/0056-hot-shard-experiment.md)
## Problems & fixes
- Docker Desktop was not running — started it.
- The tuple-counter column of the live matrix was near zero on a short run: PostgreSQL publishes statistics up to 10 s late
  → the script waits 11 s before the second snapshot.
## Verified (how)
- `hot-shard.sh` on 24 vCPU: Range 100 % on B, CPU B 99 % / A 1–3 %, ≈ 520 RPS; Buckets 47 / 53 %, ≈ 1000 RPS, 0 % errors.
- Live matrix (Buckets, 100 polls / 3000 votes): writes 55.6 / 44.4 % (X-Shard) vs 55.1 / 44.9 % (PostgreSQL).
- Re-run green on the default stack: `replication-check --shard A` and `--shard B`, `redis-outage-check`, `load.py --scenario
  write`, `kill-test`.
## Not done / next steps
- Stage 4: catalog fan-out overhead vs shard-local; cross-shard write (2PC / Saga); decide catalog behaviour when one shard
  is fully down and update `db-failure-check.py` step 3.
