# 0016. Transient database errors map to 503, not 500
**Status:** Accepted · **Date:** 2026-09-22 · **Author:** Participant 2

## Context
Stage 7 (centralized error handling) left one open item in ADR 0005: transient DB failures surfaced as 500, which
tells a client nothing about whether retrying is worthwhile.

## Decision
`GlobalExceptionHandler` maps `NpgsqlException { IsTransient: true }` and `TimeoutException` — checked recursively
through `InnerException`, since EF wraps them — to **503 Service Unavailable** with a "please retry" detail.
Everything else still falls through to 500. Both are logged (the existing `Status >= 500` branch).

## Consequences
- EF's own retry strategy (ADR 0008) runs first, so a 503 means the failure outlived several retries — a genuine
  infrastructure problem, not a blip.
- Lab 3: the load balancer can drop a node on 503 while treating 500 as an application bug.
- Lab 5: k6 can separate infrastructure failure from application errors in the error-rate breakdown.
- `/health` already reports DB state separately, so the two signals agree.
