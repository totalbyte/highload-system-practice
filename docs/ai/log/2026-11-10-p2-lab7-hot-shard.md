# 2026-11-10 — Participant 2 — lab 7 stages 3–7: distribution, Hot Shard, cross-shard, resharding, load comparison, docs
**Lab:** 7 · **Commits:** `c5af796` (stage 3); stages 4–7 not committed
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
- Stage 4: partial catalog (`X-Shard-Unavailable`), `ShardUnavailableException` fail-fast in `ReadDb`,
  `scripts/cross-shard-check.py`, `db-failure-check.py` step 3 per shard; report `docs/lab7/cross-shard.md`.
- Stage 5: `scripts/resharding-model.py`, report `docs/lab7/resharding.md`.
- Stage 6: `load-tests/scenario-shards.js`, `series-lab7.sh`, `shards-report.py`; report `docs/lab7/load-comparison.md`.
- Stage 7: README «Лабораторна 7», `docs/lab7-guide.md`, `docs/about/lab7.md`.
## Decisions (link ADRs)
- [0056](../decisions/0056-hot-shard-experiment.md), [0057](../decisions/0057-cross-shard-operations.md), [0058](../decisions/0058-resharding-model.md), [0059](../decisions/0059-sharding-load-comparison.md)
## Problems & fixes
- Docker Desktop was not running — started it.
- The tuple-counter column of the live matrix was near zero on a short run: PostgreSQL publishes statistics up to 10 s late
  → the script waits 11 s before the second snapshot.
- Stage 4: a fully stopped shard made reads wait 5–9 s for Docker DNS → fail fast from the monitor; scripts first checked
  `/health` once and hit the other backend whose monitor was still behind → wait until all of 4 round-robin answers agree.
- Stage 6: the series' report crashed on a nested-quote f-string (Python < 3.12) and `set -e` skipped restoring the
  default stack — fixed the report, restored the stack by hand.
## Verified (how)
- `hot-shard.sh` on 24 vCPU: Range 100 % on B, CPU B 99 % / A 1–3 %, ≈ 520 RPS; Buckets 47 / 53 %, ≈ 1000 RPS, 0 % errors.
- Live matrix (Buckets, 100 polls / 3000 votes): writes 55.6 / 44.4 % (X-Shard) vs 55.1 / 44.9 % (PostgreSQL).
- Re-run green on the default stack: `replication-check --shard A` and `--shard B`, `redis-outage-check`, `load.py --scenario
  write`, `kill-test`.
- Stage 4: `cross-shard-check.py`, `db-failure-check.py`, `shard-routing-check.py`, `concurrency-checks.py` ALL PASSED.
- Stage 5: model matches the formulas (modulo N/(N+1)); `--live` on the running stack.
- Stage 6: `series-lab7.sh` — 6 runs, 0 % errors (numbers in ADR 0059).
- Stage 7: the 5 Mermaid diagrams of README / reports rendered by mermaid 11.4.0 in a browser.
## Not done / next steps
- Defense rehearsal; push `lab7/sharding` and open a PR after PR #16; `labs/lab7-summary.md` after the defense.
