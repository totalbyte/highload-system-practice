# 0068. Lab 9: root cause — every catalog statement parsed and planned again; fix — Npgsql `Max Auto Prepare=20`
**Status:** Accepted · **Date:** 2026-11-18 · **Author:** Participant 2

## Context
The evidence of ADR 0067 points at H3: the replicas spend much of their one core on parsing and planning the two catalog
statements on every request, because Npgsql sends them unprepared (extended protocol, `prepared_ratio` 0), and after every
pool return `DISCARD ALL` throws away any server-side state anyway. `pgbench` with the same statements gives ×2.4 throughput
with prepared statements on the same replica. Lab 9 (2.3) asks for one targeted change that removes the confirmed cause.

## Decision
- **`Max Auto Prepare=${DB_MAX_AUTO_PREPARE:-20}`** in all four connection strings (compose): Npgsql prepares a statement
  automatically after it has been used `Auto Prepare Min Usages` times (default 5) on a physical connection, up to 20 per
  connection, replacing the least used one when full. PostgreSQL then skips parse / analyze and, after its first five
  custom plans, reuses a generic plan. Npgsql keeps prepared statements across pool returns by replacing `DISCARD ALL`
  with a reset that does not deallocate them.
- **Switch for the A/B:** `DB_MAX_AUTO_PREPARE=0` restores the configuration before lab 9. Default 20: the API has only a
  few dozen distinct statements, so the hot ones fit.
- **Not changed together with it:** no index, no SQL rewrite, no pool size change — one cause, one change (`No Reset On
  Close`, removing the count query or caching the first page would be further optimizations, each with its own A/B).

## Consequences
- First check (50 VUs, `collect.sh optimized`): 411 → 588 RPS, p95 197 → 139 ms, p99 245 → 177 ms, 0 % errors; planning on
  replica A 14.7 s → 0.07 s per window; `prepared_ratio` 100 % on both replica pools. Full A/B with repeats and the
  regression runs: ADR 0069.
- **Trade-offs:** (1) Npgsql's reset on return is now four light statements (`pg_advisory_unlock_all`, `SET SESSION
  AUTHORIZATION DEFAULT`, `RESET ALL`, `DISCARD SEQUENCES`) instead of one `DISCARD ALL` — visible in `pg_stat_statements`,
  cheap; (2) each server process keeps up to 20 prepared statements and their plans in memory (small: KB each, 30
  connections per pool); (3) a generic plan is chosen for all parameter values — fine for `status` (three values, one
  index), a risk for strongly skewed parameters; (4) a schema change under running instances can invalidate a prepared
  statement ("cached plan must not change result type") — Npgsql re-prepares it, migrations run at start before traffic;
  (5) a transaction-mode connection pooler (PgBouncer) in front would need its prepared-statement support — we have none.
- The catalog stays a fan-out (ADR 0059): it got cheaper per request, the replicas are still its bottleneck.
