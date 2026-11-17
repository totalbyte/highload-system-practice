# 0055. Lab 7: two shards, each a Primary + Replica pair; application-level Shard Router by `poll_id`
**Status:** Accepted · **Date:** 2026-11-09 · **Author:** Participant 2

## Context
Lab 7 (2.2) asks for at least two independent shards (each may be the lab 6 Primary + Replica pair) and a deterministic
Shard Router in the data access layer or a middleware. The key is `poll_id` (ADR 0054). Lab 6 code already routes every
read between a Primary and a Replica (`ReadDb`, ADR 0050–0052), and stage 3 of lab 7 must compare routing strategies
(Hot Shard with a naive one, levelled with hashing / virtual buckets).

## Decision
- **Topology:** Shard A = `postgres` + `postgres-replica` (unchanged from lab 6, plus the global `users` table and the
  `poll_ids` sequence); Shard B = `postgres-shard-b` + `postgres-shard-b-replica` (host ports 5436 / 5437), the same
  `primary-init.sh` / `replica-entrypoint.sh` with `PRIMARY_HOST`. Keeping Shard A on the old service names leaves the lab
  6 scripts and demos working; both shards are symmetric pairs, so the load comparison is fair.
- **Router in the application, not a proxy:** `Sharding/ShardRouter` computes the shard from `poll_id` alone. A proxy
  (Citus, pgcat) would hide routing from the code the lab grades and would not know our key. No shared state: every
  instance computes the same answer from the id and the configuration.
- **Strategies** (`Sharding:Strategy`, env `SHARD_STRATEGY`): `Range` (`id / RangeSize`, capped at the last shard — the
  "time interval" partitioning, kept for the Hot Shard demo), `Modulo` (`id % N`), `Hash` (`fmix64(id) % N`) and the default
  `Buckets` (`fmix64(id) % 64` → bucket map, round robin by default). Buckets are the default because resharding then moves
  whole buckets by changing the map, not every row (2.5). The hash is MurmurHash3's `fmix64`, not `GetHashCode` (random per
  process in .NET); `scripts/shardlib.py` has the same function and the scripts compare against it.
- **Single Node for 2.6:** `Sharding:ShardCount=1` (`SHARD_COUNT=1`) puts everything on Shard A with the same code path.
- **Data access:** `AppDbContext` without a shard is Shard A's Primary (users, `nextval('poll_ids')`). `ShardContexts`
  (scoped) gives `PrimaryFor(pollId)` and `ReadFor(pollId)`; each shard has its own `ReadDb`, `DbNodeMonitor` and guard
  interceptor, so lab 6 behaviour (replica reads, sticky read-after-write, primary fallback, Read-Only Mode) works per shard.
  Contexts are created lazily: a request about one poll opens connections to one shard only.
- **Catalog is scatter-gather:** every shard is queried in parallel for its first `page × pageSize` rows and its count, the
  result is merged by `(created_at, id)` desc and the page is cut from the merge. Stage 4 measures its overhead.
- **`X-Shard` header:** set by the same EF connection interceptor as `X-DB-Node`, so it shows where the request really went
  (`A`, `B`, `A,B`). Creating a poll shows `A,B` for a poll that lives on B: the id comes from Shard A first. The per-request
  marks are locked because the catalog opens connections to both shards in parallel.
- **`/health`** is 503 only when every node of every shard is down: all backends are identical, so a 503 for a dead Shard B
  would remove every backend from HAProxy and take Shard A's polls down with it.
- **Seed:** users on Shard A, poll ids from the sequence in order (the hot poll still gets id 1), each poll with its votes on
  its shard. Other shards commit before Shard A's transaction, whose `users` rows are the "already seeded" marker.

## Consequences
- Verified 2026-11-09 on a cold start (24 s, `Buckets`): seed shard A 18 polls / 1937 votes, shard B 32 / 3659 (total 5596,
  as before); `scripts/shard-routing-check.py` ALL PASSED (10 new polls on the computed shard and only there, 6 reads via both
  instances on the same shard, publish / vote / results shard-local, catalog `A,B`, every seeded poll placed correctly, no
  users on B); smoke green; restart of either shard's Primary → 200; `concurrency-checks.py` ALL CHECKS PASSED.
- **The strategy cannot change on a volume with data** (rows stay where they were written): switch with `docker compose
  down -v`. A volume from before lab 7 also needs `down -v` (old polls all sit on Shard A).
- The seed is not atomic across shards: a crash between Shard B's commit and Shard A's leaves orphan polls on B. Acceptable
  for generated data; `down -v` cleans it.
- Scripts that read the database directly must ask the poll's shard. Adapted: `concurrency-checks.py` (it also had a
  `votes JOIN users` — a distributed JOIN now). Not yet: `kill-test.py`, `load.py`, `redis-outage-check.py`,
  `replication-check.py`, `db-failure-check.py`, the counter checks in `load-tests/series*.sh`.
- Each DB node keeps the same connection budget (instances × pool ≤ 90); a backend now holds up to four pools.
