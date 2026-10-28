# 0032. Connection budget for 3 and 4+ instances: shrink the per-instance pool, keep `max_connections` 100 (lab 3)
**Status:** Accepted · **Date:** 2026-10-28 · **Author:** Participant 1 · Amends 0018

## Context
ADR 0018 set `Maximum Pool Size` 30 per instance with the rule *instances × pool ≤ 97* and left 4+ instances open:
"lower the pool size or raise `max_connections`, record it in a new ADR". Lab 3 runs 1 / 2 / 3+ instances behind HAProxy
(ADR 0031; `backend-3` in profile `scale`), and the scale-out runs (task П2-5) must not hit
`FATAL: sorry, too many clients already`.

Two facts found while checking this:
- The application role `polling` is a **superuser** (the official image makes `POSTGRES_USER` one). So the 3
  `superuser_reserved_connections` are not reserved *against the backends* — they can take all 100 slots. The budget
  must leave room for admin tools by itself.
- `DB_MAX_POOL_SIZE` is already a compose variable (`.env`), so changing the pool needs no code or image change.

## Decision
- **1–3 instances: pool 30** (unchanged). 3 × 30 = 90 leaves 10 of 100 slots for psql, pgAdmin and Adminer.
- **4+ instances: lower the pool, not raise `max_connections`.** Rule: `DB_MAX_POOL_SIZE = floor(90 / N)`, i.e. the
  backends together stay at ≤ 90 whatever N is:

  | Instances | `DB_MAX_POOL_SIZE` | Backend connections at most |
  |---|---|---|
  | 1–3 | 30 (default) | 30 / 60 / 90 |
  | 4 | 22 | 88 |
  | 5 | 18 | 90 |
  | 6 | 15 | 90 |

- Why not `postgres -c max_connections=…`: one PostgreSQL does not get faster with more connections. Each connection
  is a separate server process with its own memory, the throughput limit is the DB host's CPU and, for votes, the row
  lock on the hot `options.vote_count` row (bottleneck #1). More connections would only mean more processes waiting
  on the same lock; with the cap, extra requests wait in the Npgsql pool instead (ADR 0018) — which is the visible form
  of the "database connection pool" bottleneck the lab asks about (2.5.2). Raising the limit also needs a Postgres
  restart and changes memory sizing; shrinking the pool is one `.env` line.
- No `backend-4` service in compose: lab 3 asks for "1, 2 and 3+" instances, which `backend-3` covers. If a fourth is
  ever added, it comes with `DB_MAX_POOL_SIZE=22` in the same change.

## Consequences
- Verified 2026-10-28, three instances behind the balancer:
  - 5 cold starts in a row with all three starting together (`docker compose --profile scale down -v && … up -d`):
    every run all three UP on the HAProxy stats page after 18–19 s, `RestartCount` 0/0/0, one row in
    `__EFMigrationsHistory`, seed exactly once (500 users / 50 polls / 177 options; one "Seeded", two "Seed skipped",
    two "No migrations were applied"). The expected `fail: … SELECT migration_id` (history table not created yet,
    ADR 0022) appeared once per instance. Run 2 logged one more `fail:` entry that was not captured before the next
    `down -v`; runs 1, 3, 4, 5 had only the expected three. ADR 0022 holds for three instances.
  - 150 threads × 15 s of `GET /api/polls` through the balancer (5224 requests, all 200, split 1742 / 1741 / 1741): peak
    90 backend connections = 30 per instance; psql still connected (91 client backends incl. psql).
  - The knob works under load: with `DB_MAX_POOL_SIZE=22` the same test peaked at 66 = 22 × 3, all 200.
- The pool size is per instance, not per stack: someone running more instances with the default 30 will hit
  `too many clients` at the 4th — the runbook quirk row points here.
- Participant 2's load runs on three instances (П2-5) should show `pg_stat_activity` ≤ 90 + admin connections; that is
  the second half of П1-2's done criteria and is re-checked there.
