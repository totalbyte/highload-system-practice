# Project context

Stable background: course requirements and a summary of the team's design documents, so agents don't need to parse
the Ukrainian `.docx` files.

## Course and labs

- **Course:** High-Load Systems Engineering (4th year, 1st semester).
- **Domain:** real-time polling platform.
- **Repository:** https://github.com/totalbyte/highload-system-practice
- All 5 labs build on **the same project**:

| Lab | Topic | Requirements (short) |
|---|---|---|
| 1 | System Design + MVP | ≥3 entities, ≥5 endpoints, C4 diagram, DBMS with a volume, migrations, docker compose (one command, no manual steps), ≥3 bottlenecks, README with RACI |
| 2 | Stateless | state audit (ephemeral / shared / critical stateful), move local state to Redis/DB, ≥2 instances, `X-Instance-ID`, cross-instance consistency, `docker kill` test |
| 3 | Horizontal Scaling | Nginx/HAProxy as the single entry point, Round Robin vs Least Connections (+ asymmetric latency experiment), `/health`, node failure without 5xx, 1/2/3 instance throughput |
| 4 | Distributed Caching | Redis, Cache-Aside for a read-intensive endpoint, key schema, TTL, invalidation on writes, fallback when Redis is down, `X-Cache: HIT/MISS`, cold vs hot latency |
| 5 | Load Testing | k6/Locust in `/load-tests`, 3 scenarios (read / write / complex workflow), warm-up, ramp-up 10→200 VUs, p50/p95/p99, saturation point, 1 vs N instances, cache on/off, performance baseline card |

Full assignments: `docs/labs/Lab1..Lab5 *.md` (Ukrainian).

## Team documents in `docs/`

| File | Contents |
|---|---|
| `Lab1 - System Design (Платформа опитувань).docx` | Design doc: entities, API, high-load scenario, C4, bottlenecks, stack |
| `Lab1 - План виконання.docx` | Lab 1 execution plan: stages 1–10, participant split, submission checklist |
| `Траєкторія лаб 2-5.docx` | Why lab 1 decisions matter for labs 2–5; defense questions |

To read a `.docx` without Word: Python `zipfile` → `word/document.xml` (pandoc is not installed on Participant 1's machine).

## Design doc summary

**Entities:** User (id, username, email, passwordHash, createdAt); Poll (id, title, description, creatorId,
status draft/active/closed, isPublic, allowVoteChange, startsAt, endsAt); Option (id, pollId, text, position,
+ `vote_count` column); Vote (id, pollId, optionId, userId, createdAt). Relations: User 1-N Poll, Poll 1-N Option,
Poll/Option/User 1-N Vote. `UNIQUE(pollId, userId)` = one vote per user per poll (or an atomic change of the vote
if `allowVoteChange = true`).

**Planned API:** `POST /api/polls`, `GET /api/polls`, `GET /api/polls/{id}`, `POST /api/polls/{id}/vote`,
`GET /api/polls/{id}/results` (cached for real-time reads), `PATCH /api/polls/{id}/close` (author only),
`DELETE /api/polls/{id}` (draft only). What is actually implemented: `contracts.md`.

**Designed exception → HTTP mapping:** PollNotFoundException 404, PollClosedException 409,
DuplicateVoteException 409, ValidationException 422, UnauthorizedException 401.

**Vote business logic (design doc):** poll exists, is active and `endsAt` has not passed → option belongs to this
poll → insert Vote (unique constraint catches a repeat vote if `allowVoteChange = false`) → increment the option's
counter in the same transaction → invalidate the poll's results cache.

**High-load scenario:** thousands of users send `POST /api/polls/{id}/vote` to one active poll in the last minutes
before it ends, while a live dashboard polls `GET /results`. Loaded resources: INSERT into `votes` + unique-index
check; `UPDATE options SET vote_count = vote_count + 1` (row-level lock); the DB connection pool; aggregate reads.

**Bottleneck analysis draft (format: Component / Root Cause / Symptoms).** Superseded by the final version in
`README.md` §Bottleneck Analysis, which records each point's current mitigation state — read that one for the
defense; this draft is kept as the original design-doc wording.
1. *`vote_count` update (POST /vote, UPDATE options)* — lock contention: many transactions update the same row and
   the row lock serializes them → p99 latency spikes on POST /vote, transaction queue in `pg_locks`, possible
   deadlocks/timeouts.
2. *GET /results without cache* — every request runs COUNT/JOIN aggregation in the DB → lower RPS, higher DB CPU and
   I/O wait.
3. *Connection pool exhaustion* — the fixed-size pool drains during a vote spike because transactions from item 1
   hold connections while waiting for the lock → requests queue for a connection, API timeouts, pool timeouts.
4. *N+1 when creating a poll with many options* — one INSERT per option with a naive ORM → creation latency grows
   linearly with option count. (Mitigated: EF batches the inserts — ADR 0007.)

**Designed architecture (full vision):** Client → Backend API (REST) → PostgreSQL; Backend ↔ Redis (results cache,
rate limiting); optional RabbitMQ + async worker for vote aggregation and cache invalidation. The lab 1 MVP
implements only Client → API → PostgreSQL.

**Execution-plan decisions that must hold:** JWT from day one (no server sessions); seed script with a user pool
(lab 5 needs many distinct voters, otherwise every write returns 409); results cache **deliberately in process
memory** in lab 1 (lab 2 state-audit target); `/health` + `X-Instance-ID` early (labs 2–3).

**Storyline across labs:** the `vote_count` counter is bottleneck #1 in lab 1; an in-memory copy would diverge
between two instances in lab 2; its aggregate is cached and invalidated in lab 4; it is the likely saturation point
of the write scenario in lab 5.

## Defense questions to prepare for

Every participant is questioned about the **whole** system, not only their own part.

- **Lab 1:** architecture style, data model, scalability decisions; cold start, 5+ endpoints, data survives a DB restart.
- **Lab 2:** stateless architecture vs "no data at all"; risks of hidden affinity.
- **Lab 3:** the load balancer as a single point of failure (Keepalived/VRRP, DNS round robin).
- **Lab 4:** cache stampede / thundering herd, cache avalanche, LRU vs LFU, expiration vs invalidation.
- **Lab 5:** saturation point, coordinated omission, GC/JIT impact on latency percentiles.

## Groundwork for later labs

- **Lab 2:** state-audit candidates — the in-memory results cache, DataProtection keys (stored in the container
  filesystem; we don't use them, but they show up in logs), any static/singleton holding data. For 2 instances in
  compose, remove the fixed backend `ports` mapping or give each instance its own. Verify that two instances starting
  on an empty DB don't race on migrations (ADR 0009).
- **Lab 3:** Nginx in front of the backend; the backend stops publishing its port externally; `/health` is ready.
- **Lab 4:** Redis; keys like `polls:results:{pollId}`; invalidation on vote/close.
- **Lab 5:** k6 in `/load-tests`; log seed users in during `setup()` and share tokens via `SharedArray` (login is
  deliberately CPU-heavy); write scenario → hot poll #1; read scenario → `GET /results`.
