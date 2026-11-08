# 2026-11-08 — Participant 1 — lab 6: plan and stage 1, Primary / Replica topology
**Lab:** 6 · **Commits:** not committed (branch `lab6/replication`; Participant 1 commits each stage personally)
## Goal
Read the lab 6 assignment, agree on a plan (Participant 1 does this lab alone), implement stage 1: the replication topology.
## Done
- `docs/labs/Lab6 - Database Replication.md` (assignment moved from the `.docx`), `docs/lab6/plan.md` (6 stages).
- `postgres/primary-init.sh` (role `replicator`, slot `replica_1`, `pg_hba` line), `postgres/replica-entrypoint.sh`
  (`pg_basebackup` on an empty volume), `docker-compose.yml` (WAL settings on `postgres`, new `postgres-replica`, volume
  `pgdata-replica`, port 5435), `.env.example`.
- `scripts/replication-check.py`: topology, seed on both nodes, INSERT / UPDATE / DELETE through the API reach the
  replica, writes on the replica rejected.
- Docs: ADR 0049, runbook «Replication (lab 6)» and two troubleshooting rows, `project-context`, `CLAUDE.md`, README quick
  start, status (labs 4 and 5 marked defended, web UI merged).
## Decisions (link ADRs)
- [0049](../decisions/0049-primary-replica-topology.md): async physical streaming, `postgres` stays the Primary, bootstrap
  without manual steps, slot with a 1 GB WAL limit, no automatic failover.
- Agreed for later stages, recorded in `docs/lab6/plan.md`: Primary by default and Replica as an explicit choice; a
  results-cache miss stays on the Primary (otherwise an old aggregate is cached under the new generation, breaking ADR
  0041); Session Sticky in Redis as the Read-After-Write mechanism, no LSN verification; a node monitor only if measurements
  show Npgsql's own behaviour is too slow; measurements on Participant 1's machine with a new single-primary baseline.
## Problems & fixes
- `su-exec: not found`, the replica restarted in a loop: `postgres:17-alpine` ships `gosu`. Switched to it.
- The default project's volume `polling-platform_pgdata` already had data and no replication role. It was left untouched:
  the cold start was verified in a separate project, `COMPOSE_PROJECT_NAME=polling-lab6`.
## Verified (how)
All on project `polling-lab6`, standard stack:
- Cold start: API and replica healthy in 17 s, no manual steps; `replication-check.py` ALL PASSED (seed 500 / 50 / 177 / 5596
  on both nodes, `replay_lag` ≈ 12 ms idle, write rejected with a read-only error).
- Smoke: health 200, create 201 draft, list 200, 401 without a token, publish 200, vote 201, repeat 409, results total 1, close
  200, counter mismatches 0.
- `restart postgres`: GET 200, streaming again in ≈ 2 s. Replica stopped: health 200; a poll created meanwhile reached it after
  `start`, with no new base backup (slot). `concurrency-checks.py` ALL CHECKS PASSED, mismatches 0 on both nodes, identical
  totals. `down` / `up` without `-v`: replica data kept.
## Not done / next steps
- The application still uses only the Primary; stage 2 is next.
- Not tested: the failure path on a pre-lab-6 volume (expected: the replica restarts in a loop, the stack works, `down -v`
  fixes it) and a replica outage longer than the 1 GB WAL limit.
