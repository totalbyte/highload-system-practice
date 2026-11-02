# 0043. Lab 4: Redis down → results read straight from PostgreSQL (`X-Cache: BYPASS`), fail-fast client, no Redis persistence
**Status:** Accepted (supersedes 0027) · **Date:** 2026-11-02 · **Author:** Participant 1

## Context
Lab 2 (ADR 0027) answered a results read with **503** while Redis was down, and every Redis-touching request first
waited ~5 s — StackExchange.Redis kept the command in its backlog until its timeout. ADR 0027 explicitly left the DB
fallback and fail-fast settings for lab 4. Lab 4 (2.6.3, §4 п. 3) asks that after `docker stop redis` the backends
work directly with the database and the system stays functional (graceful degradation).

Checking the "no stale data after a Redis restart" claim of ADR 0027 showed it was wrong: the image runs with Redis
defaults (`save 3600 1 300 100 60 10000`), so `docker compose stop` writes `dump.rdb` into the container's filesystem
and `start` loads it back (`keys loaded: 24`). The "no volume → empty" argument only holds for `down` / recreate.

## Decision
- **Fallback.** `ResultsCache.GetAsync` catches `RedisConnectionException` / `RedisTimeoutException` and returns
  `ResultsCacheLookup.Unavailable` (no entry, generation `null`). `ResultsService` then reads PostgreSQL and answers
  **200** with `X-Cache: BYPASS`. Nothing is written to Redis in that case: without the generation read before the DB
  query a write could reintroduce the invalidation race (ADR 0041). Writes (`SetAsync`) and invalidation stay
  best-effort, as in ADR 0027 — a committed vote / publish / close / delete still answers with its success code.
- **Fail-fast client** (`Program.cs`): `BacklogPolicy.FailFast` — while there is no connection a command fails at once
  instead of queueing; `SyncTimeout = AsyncTimeout = 1000 ms` (default 5000) bounds a command on a connection that is
  formally open but gets no answer (hung Redis, network). A normal reply takes well under a millisecond. Reconnection
  is the client's own (`abortConnect=false`, ADR 0021); no circuit breaker of our own — with fail-fast an unavailable
  Redis costs nothing per request.
- **Redis is a pure cache: no persistence** — `command: redis-server --save "" --appendonly no`. After any restart it
  comes back empty, so an entry whose invalidation was missed during the outage cannot come back. Counters lost
  together with the values are harmless (missing counter = generation 0, no value under it).
- `/health` still ignores Redis (ADR 0021), so HAProxy keeps every node in the pool. `GlobalExceptionHandler` keeps
  mapping Redis connection failures to 503 as a safety net for any future Redis caller; the results path no longer
  reaches it. BYPASS reads are logged at Debug (a line per read); the outage itself is visible in the `Warning`
  lines of failed invalidations / writes.

## Consequences
- Verified 2026-11-02 with the updated `scripts/redis-outage-check.py` (via the LB, warm cache first), 2 runs, ALL
  PASSED: Redis stopped → `GET /results` **200 BYPASS in 68 ms** (lab 2: 503 after 5.2 s); vote 201 in 197 ms
  (lab 2: 5.9 s), stored once, the next read already counts it; publish 200 in 61 ms, the just-published poll is
  visible to others; `/health` 200; counters consistent. Redis started → first read **MISS** after 1.5 s (empty
  Redis), fresh, no backend restart.
- **Counter-test:** the same script with `CONFIG SET save "3600 1 300 100 60 10000"` at runtime → after the restart
  the first read was **HIT with `totalVotes=0`** although the outage vote was in PostgreSQL. That is the stale entry
  the `--save ""` decision prevents. (The dump was deleted afterwards.)
- **Staleness bound during degradation:** if Redis loses invalidations but does not restart (network blip, hung
  process), an entry written before the blip can be served after it for at most its TTL — ≤ 12 s for an active or
  draft poll (ADR 0041); a closed poll's entry cannot go stale. This is the one documented exception to "the next read
  after a mutation is fresh".
- **Cost of degradation:** every results read goes to PostgreSQL. The query is cheap (≤ 20 options by PK, ADR 0014),
  but at dashboard rates it takes pool connections from the vote transactions — exactly what the cache was for
  (bottlenecks №2, №3). Degraded mode keeps the system correct and available, not fast; protecting the DB during a
  long outage (rate limiting, an in-process L1 cache) is out of scope.
- DataProtection keys (ADR 0023) also live in Redis and are now lost on every Redis restart, not only on `down`. The
  API does not use protected payloads (JWT, no cookies), all instances regenerate one shared ring on demand — no
  user-visible effect.
- Smoke 25/25, `cache-race-check.py` 0 of 60, `concurrency-checks.py`, `cross-instance.sh` 8/8 pass.
