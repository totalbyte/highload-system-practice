# 0070. Startup migrations of each shard under a PostgreSQL advisory lock (amends 0009)
**Status:** Accepted · **Date:** 2026-11-18 · **Author:** Participant 2

## Context
ADR 0009 relied on the provider serializing `MigrateAsync` across instances (lock on the migrations history). During lab 9
cold starts one of the two backends sometimes crashed on start with `42704: constraint "fk_polls_users_creator_id" of
relation "polls" does not exist`: both instances had applied `ShardPollAggregate` (lab 7) on Shard A, and the second one
failed on the already dropped FK. Docker restarted it and the stack came up, but `docker compose up --wait` failed in the
meantime, which broke the evidence script.

## Decision
`DatabaseInitializer` opens the shard's connection itself, takes `pg_advisory_lock(7140002)` on it, runs `MigrateAsync` on
the same open connection and releases the lock after it. The second instance waits, then sees every migration applied.
A session-level lock is released by PostgreSQL if the instance dies. The seed keeps its own transaction-level lock
(7140001, ADR 0022). The unlock runs only after a successful `MigrateAsync` (PR review): in a `finally` it could throw on a
broken connection and hide the migration's own exception; after a failure the lock is released anyway when the connection
goes back to the pool (Npgsql resets the session with `DISCARD ALL` or `pg_advisory_unlock_all()`) or the process dies.

## Consequences
- Three consecutive cold starts after the fix: `up --wait` 0, 0 restarts of both backends, no unhandled exceptions.
- Startup of the second instance is serialized behind the first one's migrations (fractions of a second on an up-to-date
  schema).
