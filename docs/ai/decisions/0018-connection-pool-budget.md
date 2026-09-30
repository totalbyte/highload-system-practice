# 0018. Connection budget: `Maximum Pool Size` 30 per backend instance
**Status:** Accepted · **Date:** 2026-09-30 · **Author:** Participant 1

## Context
The review (`log/2026-09-22-p1-lab1-review.md`, problem 3) found that Npgsql's default pool maximum (100) equals
PostgreSQL's default `max_connections` (100, of which 3 are reserved for superusers). After a 100-thread load test
one backend instance kept ~100 idle connections and even `psql` failed with
`FATAL: sorry, too many clients already` until the backend restarted. With 2+ instances (labs 2–3) the database
would start refusing connections outright.

## Decision
- `Maximum Pool Size=30` in the connection string, configurable via `DB_MAX_POOL_SIZE` in compose / `.env`
  (`appsettings.json` for `dotnet run` uses 30 too).
- Budget rule: **instances × pool size ≤ `max_connections` − reserved (97)**. 30 × 3 instances = 90 leaves room for
  admin tools (psql, Adminer). For more instances lower the pool size or raise `max_connections`
  (`command: postgres -c max_connections=…` in compose) and record it in a new ADR.

## Consequences
- Verified 2026-09-30: after the same load tests the backend held exactly 30 connections and `psql` still
  connected; 200 parallel votes completed in ~0.5 s with no errors — requests beyond 30 wait for a pooled
  connection (Npgsql `Timeout`, default 15 s) instead of overloading PostgreSQL.
- Pool waiting is now the visible form of bottleneck #3 (connection pool exhaustion) — measurable in lab 5.
