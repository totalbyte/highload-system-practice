# 0021. Redis and two backend instances in compose (lab 2)
**Status:** Accepted, amended by 0031 (lab 3: no per-instance host ports, HAProxy on 8080) · **Date:** 2026-10-27 · **Author:** Participant 1

## Context
Lab 2 requires at least two parallel backend instances built from one codebase/container, a way to tell which
instance served a request, and moving shared state out of process memory into an external store (DB or Redis).
There is no load balancer until lab 3, and the lab 2 cross-instance scenarios ("POST → instance 1, GET → instance 2")
need the client to address each instance directly.

## Decision
- `docker-compose.yml` defines `backend-1` and `backend-2` from one YAML anchor (`x-backend`): same build, same image
  `polling-platform/backend:latest`, same environment. They differ only in `INSTANCE_ID` (`backend-1` / `backend-2`,
  so `X-Instance-ID` is readable) and the host port: `${API_PORT:-8080}` and `${API2_PORT:-8082}` (8081 is Adminer).
  Port 8080 stays, so the runbook smoke test and `requests/polls.http` work unchanged.
- Redis `redis:8.10.2-alpine` — an exact tag one patch behind the newest 8.10.x, same reasoning as ADR 0020. No
  volume: in lab 2 Redis holds only re-computable data (results cache, DataProtection keys we don't use). Host port
  `${REDIS_PORT:-6379}` for `dotnet run` and `redis-cli`, like Postgres on 5433 (ADR 0011). Healthcheck `redis-cli ping`;
  both backends wait for `service_healthy` of postgres and redis.
- `ConnectionStrings:Redis` = `redis:6379,abortConnect=false`. `Program.cs` registers **one** `IConnectionMultiplexer`
  singleton, connected at startup; the cache (Participant 2) and DataProtection keys (П1-3) both use it.
  `abortConnect=false` lets the process start while Redis is down — the client reconnects in the background.
- `/health` does **not** check Redis in lab 2: in lab 3 the load balancer would take every instance out of rotation
  when Redis fails, although PostgreSQL — the source of truth — is fine. Redis failure handling belongs to lab 4.
- In this step the application does not use Redis yet: the results cache stays in process memory on purpose, so
  Participant 2 can demonstrate the stale-results problem across instances before moving it (lab 2 task П2-2).

## Consequences
- Connection budget: 2 × `DB_MAX_POOL_SIZE` (30) = 60 ≤ 97 (ADR 0018).
- Both instances run migrations and the seed at the same time on an empty DB; whether that is safe is checked
  separately (task П1-2, follow-up to ADR 0009).
- `docker compose up` with the anchor builds the image once and reuses it for the second service.
- Lab 3 will put Nginx in front and drop the per-instance host ports.
