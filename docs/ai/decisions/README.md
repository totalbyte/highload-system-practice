# Architecture Decision Records

One decision per file, `NNNN-short-title.md`, numbered sequentially. Never delete or rewrite an accepted ADR —
if a decision changes, add a new ADR and set the old one's status to `Superseded by NNNN`.

| # | Decision | Status |
|---|---|---|
| [0001](0001-tech-stack.md) | Tech stack: C# / ASP.NET Core 10 + EF Core + PostgreSQL | Accepted |
| [0002](0002-poll-lifecycle-publish.md) | Poll lifecycle Draft → Active → Closed with an explicit `publish` endpoint | Accepted |
| [0003](0003-visibility-rules.md) | Visibility: foreign drafts → 404, unlisted polls, 403 for management | Accepted |
| [0004](0004-atomic-status-transitions.md) | Status changes via conditional UPDATE/DELETE | Accepted |
| [0005](0005-error-handling.md) | 400 vs 422, `AppException` hierarchy, ProblemDetails | Accepted |
| [0006](0006-stateless-jwt-auth.md) | Stateless JWT auth, PBKDF2 passwords | Accepted |
| [0007](0007-database-conventions.md) | bigint ids, snake_case, status as string, batched inserts | Accepted |
| [0008](0008-ef-retry-strategy.md) | EF retry strategy; transactions inside the execution strategy | Accepted |
| [0009](0009-startup-migrations-and-seed-locking.md) | Migrations + seed on startup, seed under an advisory lock | Accepted, amended by 0022 |
| [0010](0010-seed-data.md) | Deterministic seed data with a user pool and a hot poll | Accepted |
| [0011](0011-local-environment.md) | Host port 5433, GSS off, Swagger in Production | Accepted |
| [0012](0012-instance-id-and-health.md) | `X-Instance-ID` header and `/health` from lab 1 | Accepted, amended by 0019 |
| [0013](0013-lab1-in-process-results-cache.md) | Lab 1 results cache in process memory, on purpose | Superseded by 0026 |
| [0014](0014-vote-transaction-and-counter.md) | Vote in one transaction; unique index as source of truth; SQL-level counter | Accepted, amended by 0017 |
| [0015](0015-vote-and-results-api-shape.md) | Vote and results API shape | Accepted |
| [0016](0016-transient-db-errors-503.md) | Transient database errors map to 503 | Accepted, extended by 0027 |
| [0017](0017-serialize-vote-changes.md) | Vote changes serialized with `FOR UPDATE`; option rows locked in id order | Accepted |
| [0018](0018-connection-pool-budget.md) | `Maximum Pool Size` 30 per instance; instances × pool ≤ `max_connections` | Accepted, amended by 0032 |
| [0019](0019-health-check-timeout.md) | `/health` uses its own PostgreSQL probe with a 2 s timeout | Accepted |
| [0020](0020-pgadmin-pinned.md) | pgAdmin 4 pinned to `9.17.0`, server pre-registered (starts with the stack since the amendment) | Accepted, amended |
| [0021](0021-redis-and-two-backend-instances.md) | Lab 2: Redis + `backend-1`/`backend-2` from one image, ports 8080/8082, one shared `IConnectionMultiplexer` | Accepted, amended by 0031 |
| [0022](0022-concurrent-startup-verified.md) | Concurrent startup of several instances on an empty DB verified safe; no separate migrator | Accepted |
| [0023](0023-dataprotection-keys-in-redis.md) | DataProtection keys in Redis with one application name — one key ring for all instances | Accepted |
| [0026](0026-results-cache-in-redis.md) | Lab 2: results cache in Redis (`results:{pollId}`, JSON, TTL 10 s, `DEL` on invalidation), async `ResultsCache` | Accepted (supersedes 0013), amended by 0041 |
| [0027](0027-redis-unavailable.md) | Lab 2: Redis down → reads 503; invalidation and cache writes best-effort, committed changes still succeed | Superseded by 0043 |
| [0033](0033-health-checks-and-retries.md) | Lab 3: active `/health` checks (`inter 2s fastinter 500ms fall 2 rise 2`), passive `observe layer4` mark-down, `retries 2` + `redispatch 1`, L7 retries only for GET; no layer-7 observation / 5xx retries (503 trap) | Accepted |
| [0034](0034-balancing-algorithms-and-live-switch.md) | Lab 3: `roundrobin` by default; `scripts/lb-algorithm.sh` switches roundrobin / leastconn / weighted / source live (validate + SIGUSR2); `lb-distribution.py` | Accepted |
| [0037](0037-vote-backend-retries.md) | Lab 3: `be_vote` backend for `POST …/vote` — in-flight retries on another node (safe: one transaction + `UNIQUE`), own `/health` checks + `observe layer4` instead of `track`; 5xx not retried | Accepted (extends 0033) |
| [0036](0036-artificial-delay-middleware.md) | Lab 3: artificial delay on one instance via middleware (`Diagnostics:ArtificialDelayMs`, `/health` not delayed) | Accepted |
| [0041](0041-results-cache-target-keys-and-ttl.md) | Lab 4: cache only `GET /results`; keys `polling:results:v1:{pollId}:g{gen}` + generation counter (invalidation = `INCR`, fixes the lab 2 race); TTL by status (active / draft 10 s, closed 1 h) + 0–20 % jitter; verified with `cache-race-check.py` | Accepted (amends 0026) |
| [0042](0042-x-cache-header-and-cache-logs.md) | Lab 4: `X-Cache: HIT \| MISS` on `GET /results`, captured in the HAProxy log (`{HIT}`); cache operations logged at Debug, switched by `CACHE_LOG_LEVEL` | Accepted |
| [0043](0043-redis-down-fallback-to-db.md) | Lab 4: Redis down → results from PostgreSQL with `X-Cache: BYPASS` (200, ~70 ms instead of 503 after 5 s); fail-fast client (`BacklogPolicy.FailFast`, 1 s timeouts); Redis without persistence (`--save ""`) | Accepted (supersedes 0027) |
| [0044](0044-single-flight-against-cache-stampede.md) | Lab 4: single-flight per instance against Cache Stampede — concurrent misses for one (poll, generation) share one DB load in its own scope; not for BYPASS; 6.7–14.4 → ≈ 2 DB loads per invalidation | Accepted |
| [0045](0045-load-test-environment.md) | Lab 5: k6 `grafana/k6:1.3.0` in Docker inside `app-network` (targets `lb:8080`), every component pinned to its own cores (`cpuset` + limits), k6 on cores 16–23; overlay `load-tests/docker-compose.loadtest.yml` | Accepted |
| [0046](0046-results-cache-switch.md) | Lab 5: `ResultsCache:Enabled=false` → results read straight from the DB, `X-Cache: DISABLED`; invalidation keeps running | Accepted |
| [0047](0047-fresh-stack-per-load-run.md) | Lab 5: every measured run on a fresh stack (`down -v` → `up`, same seed) — the first series drifted (C grew `polls` 50 → 17k, B ≈ 833k hot-row updates) | Accepted |

Template:

```markdown
# NNNN. Title
**Status:** Proposed | Accepted | Superseded by NNNN · **Date:** YYYY-MM-DD · **Author:** Participant N
## Context
## Decision
## Consequences
```
| [0048](0048-web-ui.md) | Web UI: React + Vite + TS in an nginx container behind HAProxy (same origin, no CORS); favorites in localStorage; `GET /api/polls/{id}/vote` | Accepted |
