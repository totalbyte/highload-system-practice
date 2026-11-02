# 0042. Lab 4: `X-Cache: HIT | MISS` header, cache logs at Debug, captured in the HAProxy log
**Status:** Accepted · **Date:** 2026-11-02 · **Author:** Participant 1

## Context
Lab 4 (2.6.1) asks to make the data source visible during the demo — a response header such as `X-Cache: HIT / MISS`
or logging of cache operations. Since lab 3 every request goes through HAProxy, whose log already shows the instance
and the timings of each request (ADR 0031).

## Decision
- **Header.** `GET /api/polls/{id}/results` answers with `X-Cache: HIT` (served from Redis, no DB query) or
  `X-Cache: MISS` (read from PostgreSQL and stored). `ResultsService.GetAsync` returns `PollResultsRead(response,
  CacheResult)`; the controller sets the header — one line, no logic. `BYPASS` (Redis unavailable) comes with the
  fallback, П1-5. Only on successful responses: a 404 / 503 is an exception handled globally and carries no header.
  No other endpoint is cached (ADR 0041), so no other endpoint sends it.
- **HAProxy log.** `capture response header X-Cache len 8` in `fe_api`; with `option httplog` the value appears as
  `{HIT}` / `{MISS}` next to the server name and `%Tr` / `%Ta`, `{}` for other endpoints. `docker compose logs lb`
  thus shows source, instance and latency of every results read in one line — the demo and cold / hot timing need
  nothing else.
- **Backend logs at `Debug`.** `ResultsCache` logs `HIT` / `MISS` (poll, generation), `STORE` (generation, status,
  TTL) and `INVALIDATE` (generation `n -> n + 1`). Under load that is a line per request, so the default stays
  `Information`; for the demo `CACHE_LOG_LEVEL=Debug docker compose up -d` (env
  `Logging__LogLevel__PollingPlatform.Api.Results`, default `Information`). Warnings about an unavailable Redis stay
  at `Warning` and are always on.

## Consequences
- Verified 2026-11-02 through the LB: MISS (backend-2) → HIT (backend-1) → HIT (backend-2) → vote 201 → MISS
  (backend-1) → HIT; the LB log shows `{MISS}` / `{HIT}`, a 404 shows `{}`; with Debug the backend logs show
  `MISS → STORE g1 → INVALIDATE 1 -> 2 → MISS g2 → STORE g2`; back at `Information` — no cache lines. Smoke 25/25.
- A read of a non-existent poll is a MISS every time (nothing to store, 404) — no negative caching. Repeated reads of
  random ids would all reach PostgreSQL (cache penetration); out of scope, mentioned for the defense.
