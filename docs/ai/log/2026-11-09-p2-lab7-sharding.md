# 2026-11-09 — Participant 2 — lab 7 stages 1–2: shard key, Shard B, Shard Router
**Lab:** 7 · **Commits:** not committed
## Goal
Start lab 7 (sharding): choose the dataset and the shard key, plan the stages, bring up a second shard.
## Done
- Assignment converted to `docs/labs/Lab7 - Data Scaling Sharding Partitioning.md`; stage plan `docs/lab7/plan.md`.
- ADR 0054: poll aggregate by `poll_id`; `users` stays unsharded on Shard A.
- Branch `lab7/sharding` from `origin/lab6/replication`.
- `docker-compose.yml`: `postgres-shard-b` + `postgres-shard-b-replica` (5436 / 5437); `postgres/replica-entrypoint.sh`
  takes `PRIMARY_HOST` (default `postgres`, so Shard A is unchanged).
- Stage 2: `Sharding/` (ShardRouter, Shard, ShardContexts), per-shard `ReadDb` / `DbNodeMonitor`, `X-Shard`, catalog
  scatter-gather, poll ids from sequence `poll_ids`, `creator_username`, FKs to `users` dropped (migration
  `ShardPollAggregate`), seed and migrations on every shard; `scripts/shardlib.py`, `scripts/shard-routing-check.py`;
  `concurrency-checks.py` asks the poll's shard.
## Decisions (link ADRs)
- [0054](../decisions/0054-shard-dataset-and-key.md), [0055](../decisions/0055-shard-topology-and-router.md)
## Problems & fixes
- Routing check expected `X-Shard=B` for new polls on B, got `A,B`: correct — creation takes the id from Shard A first.
- `concurrency-checks.py` failed for polls on B: it read only `postgres` and joined `votes` with `users` (now a distributed
  JOIN) — rewritten to ask the poll's shard and look the user up on Shard A.
## Verified (how)
- `docker compose config -q`; Shard B pair: streaming / async, slot `replica_1` active, replica in recovery.
- Cold start (old DB volumes removed, 24 s): seed A 18 / 1937, B 32 / 3659; `shard-routing-check.py` ALL PASSED; runbook
  smoke (health, login, create, list, 401, restart of each shard's Primary → 200); `concurrency-checks.py` ALL CHECKS PASSED.
## Not done / next steps
- Adapt the remaining direct-DB scripts to shards (`kill-test`, `load`, `redis-outage-check`, `replication-check`,
  `db-failure-check`, `load-tests/series*.sh`).
- Stage 3: distribution matrix, Hot Shard with `Range`, levelling with `Hash` / `Buckets`.
