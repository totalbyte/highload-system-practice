# 0022. Concurrent startup of several instances on an empty DB is safe — no separate migrator
**Status:** Accepted · **Date:** 2026-10-27 · **Author:** Participant 1 · Amends 0009

## Context
ADR 0009 left one point unverified: with two or more backend instances (lab 2, ADR 0021) every instance runs
`Database.MigrateAsync()` and the seed at startup, at the same moment, against the same empty database. If they raced,
the fix would be a one-off `migrator` compose service that runs before the backends.

## Decision
Keep migrations and the seed in the backend startup; **no `migrator` service**. Verified on 2026-10-27 (EF Core 10,
Npgsql EF provider 10.0.3, PostgreSQL 17): 12 cold starts (`docker compose down -v && up -d`) of `backend-1` and
`backend-2` starting simultaneously, 7 of them with `log_statement=all` on PostgreSQL (temporary override file, not
in the repo) to see the SQL of both instances:
- Every run: both instances healthy, `RestartCount` 0, exactly one row in `__EFMigrationsHistory`, the seed applied
  once (500 users / 50 polls / 177 options), the other instance logged "No migrations were applied" and "Seed skipped".
- Migrations are serialized by the provider: each instance runs `LOCK TABLE "__EFMigrationsHistory" IN ACCESS
  EXCLUSIVE MODE` inside a transaction; the second one waits, then reads the history and applies nothing.
- The seed is serialized by our `pg_advisory_xact_lock` (ADR 0009) — seen in the statement log for both instances.
- Known harmless race, seen in 2 of 12 runs: both instances run `CREATE TABLE IF NOT EXISTS "__EFMigrationsHistory"`
  at the same instant and PostgreSQL rejects one with `23505 duplicate key ... "pg_type_typname_nsp_index"` (a known
  PostgreSQL behaviour of concurrent `IF NOT EXISTS`). The provider rolls back and continues straight to the `LOCK
  TABLE` step — the table exists either way. It appears in the backend log as a `fail: ... Failed executing
  DbCommand` for that `CREATE TABLE`.

## Consequences
- The graded "one `docker compose up`, no manual steps" holds with several instances; adding a third instance in
  lab 3 needs no change here.
- Two expected `fail:` entries may appear on a cold start (`SELECT ... FROM "__EFMigrationsHistory"` before the table
  exists, and occasionally the `CREATE TABLE IF NOT EXISTS` race above). Documented in the runbook quirks.
- If a future migration is slow (minutes), the waiting instances simply start later; revisit a separate migrator only
  if startup time or zero-downtime deploys become a requirement.
