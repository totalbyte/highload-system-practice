# 0012. `X-Instance-ID` header and `/health` from lab 1
**Status:** Accepted · **Date:** 2026-09-22 · **Author:** Participant 1

## Context
Lab 2 requires identifying which instance served a request; lab 3 requires a health endpoint for the load balancer.
The execution plan recommends adding both early (≈20 lines).

## Decision
- Middleware adds `X-Instance-ID` to every response: env `INSTANCE_ID` if set, otherwise the machine name
  (= container hostname).
- `GET /health` runs ASP.NET health checks including a DB connectivity check (`AddDbContextCheck`) and returns
  `{status, instance, checks, durationMs}`; 200 when healthy, 503 when not.

## Consequences
- Ready for lab 2 cross-instance demos and lab 3 Nginx health checks without further changes.
