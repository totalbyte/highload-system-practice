# 0050. Lab 6: read/write separation in the application, Primary by default
**Status:** Accepted · **Date:** 2026-11-08 · **Author:** Participant 1

## Context
Lab 6 (2.2, 2.3) needs mutations on the Primary and eventually consistent reads on the Replica, either in the application
or in a proxy. A proxy (Pgpool-II) would parse SQL and could not tell apart two identical `SELECT`s of which only one may be
stale, for example a catalog read and the read that decides a vote. Only the application knows that.

## Decision
- **`ReadDb.Eventual`** (`Data/ReadDb.cs`) is the only way to the replica. All other code keeps using `AppDbContext`, which
  is the Primary. A forgotten classification therefore costs load on the Primary, not stale data.
- **A second instance of `AppDbContext`, not a second type:** the replica uses the same model with other options, so
  `dotnet ef` keeps working without `--context`. It has its own Npgsql pool of `DB_MAX_POOL_SIZE`; the budget of ADR 0032
  (instances × pool ≤ 90) now applies to each node separately.
- **Classification:**

| Node | Operations | Why |
|---|---|---|
| Replica | catalog `GET /api/polls`, details `GET /api/polls/{id}`, results when the cache is switched off | a short lag is harmless; the answer is not stored anywhere |
| Primary | login, registration, `/me` | authentication must see the current user and password |
| Primary | vote, publish, close, delete, and the checks before them | a stale check would reject a vote in a poll that was just published, or accept one in a closed poll |
| Primary | the response returned after a write | the client must get what it has just written |
| Primary | `GET /api/polls/{id}/vote` | the user's own vote |
| Primary | results on a cache MISS and BYPASS | see below |

- **Results with the cache on are read from the Primary.** After a vote the generation grows (ADR 0041). A MISS reading the
  replica may not see that vote yet, and it would store the old aggregate under the new generation, so every user would get
  stale results until the TTL ends. Lag would stop being a few milliseconds for one reader and become seconds for everyone.
  The cache already takes most of this load off the database. BYPASS stays on the Primary too, so a vote stays visible on the
  next read while Redis is down (ADR 0043).
- **`X-DB-Node: primary | replica | primary,replica`**, absent when no database was touched (cache HIT). An EF connection
  interceptor sets it when a connection really opens, so it reports what happened and not what was intended. A request
  that joined another request's single-flight load (ADR 0044) opens nothing, so the controller marks MISS as `primary`.
- **`ReadReplica:Enabled=false`** (`READ_REPLICA_ENABLED`) or an empty `ConnectionStrings:PostgresReplica` makes
  `ReadDb.Eventual` return the Primary: the Single Primary configuration for 2.6. `dotnet run` has no replica string, so it
  also runs on the Primary only.

## Consequences
- Verified 2026-11-08: `scripts/rw-routing-check.py` passes (10 operations on the expected node; 300 catalog reads: replica
  ≈ +1206 transactions, primary ≈ +30, stable in 3 runs). `concurrency-checks`, `cache-race-check` (0 of 60), `cache-stampede-check` (2.1 loads),
  `redis-outage-check`, `cache-demo`, `kill-test`, `cross-instance.sh` (8/8), `replication-check` all pass; counter
  mismatches 0.
- The claim about cache poisoning is reasoning from ADR 0041, not a measurement: the variant with a MISS on the replica was
  not built. On an idle stack lag is about 10 ms, so it would rarely show without an artificial delay.
- Scenario A with the cache on gets replica traffic only from its catalog and details requests (40 % of the mix). The read
  scaling comparison therefore also needs a cache-off run (stage 5).
- **Not solved yet:** an author can get 404 for a poll created a moment ago, because the next `GET` goes to the replica (stage
  3, Read-After-Write). Replica or Primary loss still fails requests, and `/health` checks only the Primary (stage 4).
