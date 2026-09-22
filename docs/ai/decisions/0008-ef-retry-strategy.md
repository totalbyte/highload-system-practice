# 0008. EF retry strategy; transactions inside the execution strategy
**Status:** Accepted · **Date:** 2026-09-22 · **Author:** Participant 1

## Context
The lab 1 defense restarts the DB container to prove persistence. Observed: the first request after
`docker compose restart postgres` returned 500, because pooled connections were dead.

## Decision
`UseNpgsql(..., npgsql => npgsql.EnableRetryOnFailure(maxRetryCount: 3, maxRetryDelay: 2s))`.

## Consequences
- Verified: no 500s after repeated Postgres restarts.
- **Any explicit transaction (`BeginTransactionAsync`) must run inside
  `db.Database.CreateExecutionStrategy().ExecuteAsync(...)`**, otherwise EF throws `InvalidOperationException`.
  The retried block must be idempotent and should call `db.ChangeTracker.Clear()` first. Reference implementation:
  `DataSeeder.SeedAsync`. This applies to the vote transaction (stage 5).
