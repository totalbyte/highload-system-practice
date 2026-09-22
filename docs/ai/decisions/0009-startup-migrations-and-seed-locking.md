# 0009. Migrations + seed on startup, seed under an advisory lock
**Status:** Accepted · **Date:** 2026-09-22 · **Author:** Participant 1

## Context
Lab 1 requires the stack to start with one command and no manual steps. From lab 2 on, several backend instances
start at the same time against one database.

## Decision
- On startup the backend runs `Database.MigrateAsync()` (`Database:MigrateOnStartup`, default true) and then the seed
  (`Seed:Enabled`). See `Data/DatabaseInitializer.cs`.
- The seed runs in one transaction that first takes `pg_advisory_xact_lock(7140001)` and only inserts if `users` is
  empty, so concurrent instances can't seed twice.

## Consequences
- **Unverified:** EF Core 9+ has a migration-locking mechanism for concurrent `MigrateAsync`, but it was not tested
  with Npgsql. In lab 2, test two instances starting simultaneously on an empty DB; if they race, move migrations to
  a one-off compose service (or an init container) and record a new ADR.
