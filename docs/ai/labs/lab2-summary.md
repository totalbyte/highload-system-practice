# Lab 2 summary — Stateless architecture

**Status:** all tasks merged into `main` (PR #2, #4, #3, 2026-10-27); end-of-lab code = `2633293`. Defense rehearsal
(С-5) dry-run 2026-10-28 on the current `main`, all demos green; the participants' own rehearsal and the defense
itself are not recorded yet. Long-form guide for the defense (Ukrainian): [`docs/lab2-guide.md`](../../lab2-guide.md).

## What was built
- **Two instances** `backend-1` / `backend-2` from one YAML anchor (one image, same env, differ only in
  `INSTANCE_ID`; lab 2 ports 8080 / 8082), `X-Instance-ID` on every response. **Redis** `redis:8.10.2-alpine`, no
  volume, one shared `IConnectionMultiplexer` (ADR 0021).
- **State audit** of the whole `src/` in the lab's three categories + a code grep for in-process state (30 hits on
  `main` after lab 2, every hit explained in README «Аудит коду»; 32 since lab 3 — `ArtificialDelayExtensions`).
- **Removed critical dependencies:** results cache `IMemoryCache` → Redis (`results:{pollId}`, JSON, TTL 10 s,
  `DEL` on vote / publish / close / delete; ADR 0026, supersedes 0013); DataProtection keys from container files →
  Redis list `DataProtection-Keys`, one application name (ADR 0023).
- **Redis down** (ADR 0027): reads 503 ProblemDetails, invalidation and cache writes best-effort (a committed vote is
  never reported as failed), recovery without a backend restart.
- **Concurrent cold start** of several instances on an empty DB verified safe (12 runs; EF `LOCK TABLE` + our
  advisory lock), no separate migrator (ADR 0022, amends 0009).
- **Stateless Request Flow** for `POST /api/polls/{id}/vote` (table + sequence diagram), C4 component diagram,
  multi-instance deployment docs — all in README «Лабораторна 2».

## Proof (scripts, stdlib Python / curl)
| Script | Shows | Last result |
|---|---|---|
| `scripts/cross-instance.sh` / `requests/cross-instance.http` | 8-step chain across instances, no sticky sessions | 8 / 8 |
| `scripts/results-cache-demo.py` | "before" (stale counts, stale 404 after publish) vs "after" (same `generatedAt` on both) | `no` / `no` |
| `scripts/concurrency-checks.py` | 200 simultaneous votes, 40 parallel changes, opposite changes — split across both processes | all OK |
| `scripts/kill-test.py [--stop]` | kill / stop `backend-1` in the middle of 800 votes | 800 / 800 stored once, counters 0 |
| `scripts/redis-outage-check.py` | Redis stopped / started | 503 on reads, 201 on votes, back in ~1–2 s |
| manual `curl` | no sessions: token from one instance works on the other, tampered → 401; other JWT secret → 401 | as expected |

## Final decisions
ADR 0021 (Redis + two instances; amended by 0031 in lab 3), 0022 (concurrent startup), 0023 (DataProtection keys),
0026 (results cache in Redis), 0027 (Redis unavailable). Lab 1 decisions the lab relies on: 0006 (JWT), 0014 / 0017
(vote transaction, `FOR UPDATE`), 0018 (connection budget), 0019 (`/health`).

## How to demo lab 2 now (after lab 3)
Backends no longer publish ports; use the debug overlay:
`docker compose down -v && docker compose -f docker-compose.yml -f docker-compose.debug.yml up -d --build`, then
`export API1=http://127.0.0.1:8091 API2=http://127.0.0.1:8092` for the Python scripts and
`I1=http://localhost:8091 I2=http://localhost:8092 bash scripts/cross-instance.sh`. Exact lab 2 code:
`git switch --detach 2633293` (ports 8080 / 8082, scripts without variables). Step-by-step script: guide §11.

## Defense notes
- Two must-know topics: stateless ≠ "no data"; hidden affinity risks (our three examples: in-memory cache incl. the
  stale-404 access decision, per-instance JWT secret, file-based DataProtection keys).
- All consistency guarantees live in PostgreSQL (transaction, `UNIQUE`, `FOR UPDATE`, advisory lock), never in
  process locks.
- Known limits, deliberately left for lab 4: invalidation race (stale ≤ 10 s), no DB fallback when Redis is down,
  ~5 s per Redis-touching request during an outage.

## Leftovers
- С-5: the participants' own cold-start rehearsal (guide §11 checklist), then the defense; record what was asked here.
