# 0026. Results cache in Redis, shared by all instances (lab 2)
**Status:** Accepted (supersedes 0013) · **Date:** 2026-10-27 · **Author:** Participant 2

## Context
ADR 0013 kept the results cache in process memory on purpose, as the lab 2 state-audit target. With two instances
(ADR 0021) the "before" demo (`scripts/results-cache-demo.py`, П2-2) showed two failures, both stable over three runs:
after a vote through backend-1, backend-2 kept serving the old count with the old `generatedAt` until the 10 s TTL;
after a publish through backend-1, backend-2 kept answering **404** to non-authors, because the cached entry still
said `draft`. Invalidation only reached the instance that handled the write. That is hidden affinity: the answer
depends on which instance the request lands on.

## Decision
- `ResultsCache` stores entries in Redis through the shared `IConnectionMultiplexer` from ADR 0021, using `IDatabase`
  directly — no new packages, nothing added to the `.csproj`.
- Key stays `results:{pollId}`; value is `CachedPollResults` as UTF-8 JSON (`System.Text.Json`, web defaults, enum as
  camelCase string — readable in `redis-cli`, independent of enum member order); TTL 10 s set atomically with the
  value (`SET … EX`); invalidation is `DEL`.
- The API becomes asynchronous: `GetAsync` / `SetAsync` / `InvalidateAsync`. All invalidation points stay as they were:
  a vote (after commit), publish, close, delete.
- `AddMemoryCache()` is removed. `ResultsCache` remains a singleton: it holds no data, only a reference to the shared
  connection.
- The entry still carries `CreatorId`, so the draft-visibility check on a hit costs no DB query (ADR 0015).
- Out of scope for lab 2 by the project's own rule, left for lab 4: the key schema, the TTL rationale, `X-Cache`,
  cold/hot latency, fallback to the DB when Redis is down, cache-stampede protection, and the invalidation race below.
  What a Redis outage returns in lab 2 is decided separately (П2-4).

## Consequences
- Verified 2026-10-27: the same demo now reports **no** stale counts and **no** 404 in three runs; both instances
  return the identical `generatedAt`, i.e. one instance computed the aggregate and the other served that very copy.
  `TTL results:<id>` ≤ 10 after a read, the key is gone after a vote; the response format is unchanged. 120 parallel
  first votes, 40 parallel changes by one user and 100 opposite changes, split across both instances — all as
  expected, per-option counters exact, no deadlocks.
- The race "aggregate computed before a vote commits, written after its invalidation" remains: a stale entry can live
  up to the TTL. Moving to Redis does not fix it; it is a lab 4 topic.
- Every results read and every write now makes one Redis round-trip; with Redis down these calls fail — handled in П2-4.
