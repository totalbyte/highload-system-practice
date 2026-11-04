# 0046. Lab 5: `ResultsCache:Enabled` switch for cache-off runs
**Status:** Accepted · **Date:** 2026-11-02 · **Author:** Participant 2

## Context
Lab 5 (2.6) asks for the read scenario with "Cache Disabled / Cold Cache" vs "Cache Enabled / Warm Cache", with latency
and the load on the database. Stopping Redis is not the same thing: that is the fallback path of ADR 0043 (fail-fast
errors, warnings in the logs) and also drops DataProtection keys and invalidation.

## Decision
- Config `ResultsCache:Enabled` (default `true`), env `ResultsCache__Enabled`, compose variable `RESULTS_CACHE_ENABLED`.
- `false`: `ResultsService` reads PostgreSQL directly on every request, same visibility check, header
  **`X-Cache: DISABLED`**; no lookup, no store, no single-flight.
- Invalidation keeps running when the cache is off: otherwise, after switching it back on, Redis could serve entries
  written before the switch while votes were not invalidating them (closed polls keep a 1 h TTL).

## Consequences
- Switching needs a restart of the backends (`RESULTS_CACHE_ENABLED=false docker compose … up -d backend-1 backend-2`).
- Verified 2026-11-02: three reads → `DISABLED`, `generatedAt` changes on every read; the app smoke test fails exactly
  the "served from the cache" check and passes everything else; switched back → `MISS` / `HIT` again.
