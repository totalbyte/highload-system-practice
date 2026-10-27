# 0027. Redis unavailable (lab 2): reads → 503, cache writes and invalidation are best-effort
**Status:** Accepted (extends 0016) · **Date:** 2026-10-27 · **Author:** Participant 2

## Context
Since ADR 0026 every results read and every write goes through Redis. Measured with `docker compose stop redis`
before this change: `GET /results` → **500** after ~5.4 s; `POST /vote` → **500** after ~5.9 s although the vote was
already **committed** in PostgreSQL. The client sees a failure, retries, and gets 409 for a vote that went through.
The ~5 s is StackExchange.Redis keeping the command in its backlog while waiting for a connection
(`abortConnect=false`, ADR 0021). Lab 2 asks only that a new external service does not produce 500s or mislead the
client; a real fallback to the database is lab 4.

## Decision
- **Reads fail with 503.** `RedisConnectionException` / `RedisTimeoutException` (checked recursively through inner
  exceptions, before the generic `TimeoutException`) map to **503** ProblemDetails in `GlobalExceptionHandler`, like
  transient DB errors (ADR 0016). The detail names the dependency: "The cache is temporarily unavailable" vs "The
  database …". No fallback to the DB in lab 2.
- **Invalidation is best-effort.** `ResultsCache.InvalidateAsync` catches those two exceptions, logs a one-line
  warning (no stack trace) and returns. It runs only after the change is committed, so a vote, publish, close or
  delete returns its normal success code. Handling it inside `ResultsCache` covers all four call sites at once,
  including the three in `PollService`, without touching them.
- **Writing a computed entry is best-effort** too (`SetAsync`): the response is already computed from the DB, and
  returning it beats a 503. In practice `GetAsync` fails first while Redis is down; this covers a Redis drop between
  the read and the write.
- Any other `RedisException` (e.g. a server error from a wrong command) is a bug and still ends as 500.

## Consequences
- Verified with `scripts/redis-outage-check.py` (2 runs): Redis stopped → `GET /results` 503 (~5.2 s); `POST /vote`
  201 (~5.9 s), stored exactly once; `PATCH /publish` 200; per-option counters consistent. Redis started → results
  200 within ~1.6 s and include the outage vote; no backend restart.
- **Staleness bound:** if invalidation fails during a short blip and Redis keeps its data, the stale entry lives at
  most the 10 s TTL. If Redis restarts, it comes back empty (no volume, ADR 0021) — nothing stale at all.
- **Every request that touches Redis waits ~5 s during an outage** (the client's backlog timeout). That tolerates
  short blips (a Redis restart takes well under a second) but makes a long outage slow. Fail-fast backlog settings
  belong to the connection setup (Participant 1's `Program.cs` block) and come together with the DB fallback in lab 4.
- `/health` still does not check Redis (ADR 0021): with PostgreSQL up, an instance can serve everything except cached
  reads, so the load balancer in lab 3 must not drop it.
