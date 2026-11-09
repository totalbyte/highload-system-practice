# 0049. Lab 6: asynchronous streaming replication, one replica bootstrapped by `pg_basebackup`
**Status:** Accepted · **Date:** 2026-11-08 · **Author:** Participant 1

## Context
Lab 6 (2.1) needs a Primary that takes every mutation and a read-only Replica that replays its WAL. The stack must still
start with `docker compose up` and no manual steps. Scripts in `scripts/` and `load-tests/` address the database as the
compose service `postgres`.

## Decision
- **Service names:** `postgres` stays the Primary, `postgres-replica` is new. Renaming the Primary would touch every
  script for no benefit. The replica's host port is 5435: 5434 is what Participant 2's `.env` already uses for the Primary
  (runbook).
- **Replication mode:** physical streaming, asynchronous (`synchronous_standby_names` stays empty, `COMMIT` does not wait
  for the replica). The lab asks to study replication lag, and a synchronous standby would make one replica's outage block
  every vote. Logical replication is not needed: the replica is a full read-only copy.
- **Bootstrap:** `postgres/primary-init.sh` (in `docker-entrypoint-initdb.d`) creates the role `replicator` (`REPLICATION
  LOGIN` only, no application rights), the physical slot `replica_1` and a `pg_hba` line for it. `postgres/replica-entrypoint.sh`
  waits for the Primary over TCP, runs `pg_basebackup -R -S replica_1` on an empty volume, then calls the image's
  entrypoint. The TCP wait is deliberate: during first initialization the Primary's socket-based healthcheck is already
  green while the role and the slot do not exist yet.
- **Slot with a limit:** the slot keeps WAL for a stopped replica, so a short outage needs no new base backup.
  `max_slot_wal_keep_size=1GB` bounds it: after a long outage the replica loses the slot and needs a new base backup, but
  the Primary's disk does not fill up.
- **`hot_standby_feedback=on`:** the Primary keeps rows the replica is still reading, so reads are not cancelled by
  conflicts with WAL replay. The cost is some bloat on the Primary while long reads run on the replica.
- **No automatic failover / promotion:** 2.5 asks for Read-Only Mode when the Primary is lost. Leader election stays in
  the theory part of the defense.

## Consequences
- Verified 2026-11-08, cold start: API healthy and replica healthy in 17 s. `scripts/replication-check.py` passes:
  streaming / async, slot active, migrations and seed on both nodes (500 / 50 / 177 / 5596 rows), INSERT / UPDATE / DELETE
  through the API replayed, a write on the replica rejected with "cannot execute UPDATE in a read-only transaction".
  `replay_lag` ≈ 12 ms on an idle stack (the script's 240–380 ms is mostly `docker compose exec` overhead, so it is only an
  upper bound).
- `docker compose restart postgres`: the replica reconnects by itself (≈ 2 s). `stop` / `start` of the replica: it catches
  up through the slot without a new base backup. `concurrency-checks.py` passes, per-option counter mismatches are 0 on
  both nodes, `down` / `up` without `-v` keeps the replica's data.
- **A volume created before lab 6 does not get the role and the slot**, because init scripts run only on an empty data
  directory. The replica then restarts in a loop while the rest of the stack works: run `docker compose down -v` once.
- `pg_basebackup` removes a partial copy when it fails, but not after a `SIGKILL`; if that happens, `docker compose down -v`
  is the cure. Guarding against it would need a check that also wipes a promoted replica, so it is left out.
- Wiping only the Primary's volume leaves the replica on a different history. `down -v` removes both, which is the only
  documented way.
- At this stage the application still talks only to the Primary; routing comes with the next ADRs.
