# Polling Platform — High-Load Systems course project

Two-person university project for "High-Load Systems Engineering" (4th year). A real-time polling platform
(User, Poll, Option, Vote) that grows over 7 labs: MVP → stateless → horizontal scaling → distributed caching →
load testing → database replication → sharding. **Participant 1** ("platform": infra, DB, auth, poll lifecycle);
**Participant 2** — teammate ("voting core": votes, results, caching, error handling, bottleneck analysis).
Both are questioned about the *whole* system at every lab defense.

Course materials and team documents are in Ukrainian ("Учасник 1/2" = Participant 1/2). Agent docs are in English.

## Start of every session

1. Read [`docs/ai/status.md`](docs/ai/status.md) — current state, who is doing what, next steps.
2. Run `git log --oneline -15` and `git status`. **The code is the source of truth**; docs may lag behind it.
3. Ask the user which participant they are and what the goal of the session is (unless obvious).
4. Open other docs only when the task needs them (map below). Don't read the whole `docs/` tree up front.

## Knowledge map

| File | Read when |
|---|---|
| [`docs/ai/status.md`](docs/ai/status.md) | Always, at session start |
| [`docs/lab2/participant-1.md`](docs/lab2/participant-1.md), [`participant-2.md`](docs/lab2/participant-2.md) | Lab 2 task list of the participant you are working with (Ukrainian) |
| [`docs/lab3/participant-1.md`](docs/lab3/participant-1.md), [`participant-2.md`](docs/lab3/participant-2.md) | Lab 3 task list of the participant you are working with (Ukrainian) |
| [`docs/lab4/participant-1.md`](docs/lab4/participant-1.md) | Lab 4 task list (Ukrainian) — Participant 1 does lab 4 alone, by agreement |
| [`docs/lab5/plan.md`](docs/lab5/plan.md), [`load-tests/README.md`](load-tests/README.md) | Lab 5 stages (both participants, one branch) and how to run k6 / the full measurement series |
| [`docs/lab6/plan.md`](docs/lab6/plan.md), [`load-comparison.md`](docs/lab6/load-comparison.md) | Lab 6 stages and load comparison (Ukrainian) — Participant 1 does lab 6 alone, by agreement |
| [`docs/lab7/plan.md`](docs/lab7/plan.md), [`hot-shard.md`](docs/lab7/hot-shard.md) | Lab 7 stages and the distribution / Hot Shard report (Ukrainian) — sharding the poll aggregate by `poll_id`, Participant 2 |
| [`docs/ai/project-context.md`](docs/ai/project-context.md) | You need lab requirements, the design-doc summary, the high-load scenario, bottlenecks, defense questions |
| [`docs/ai/contracts.md`](docs/ai/contracts.md) | You touch the API, DB schema, or code another participant depends on; open questions for Participant 2 |
| [`docs/ai/runbook.md`](docs/ai/runbook.md) | Running, testing, migrations, seed data, troubleshooting |
| [`docs/ai/decisions/`](docs/ai/decisions/README.md) | Before changing an established approach (why things are the way they are) |
| [`docs/ai/log/`](docs/ai/log/) | You need the history of a specific session (normally not needed) |
| [`docs/ai/labs/`](docs/ai/labs/) | Summaries of finished labs |
| `src/PollingPlatform.Api/CLAUDE.md` | Auto-loaded when working in the code: structure and coding conventions |
| [`docs/lab1-guide.md`](docs/lab1-guide.md) | Long-form guide to lab 1 for the participants (Ukrainian): architecture, data model, voting logic, why each decision was made, defense Q&A |
| [`docs/lab2-guide.md`](docs/lab2-guide.md) | Lab 2 defense guide (Ukrainian): stateless concepts, audit, removed in-memory state, how to run the lab 2 demos after lab 3, step-by-step defense script, Q&A |
| [`docs/lab3-guide.md`](docs/lab3-guide.md) | Lab 3 defense guide (Ukrainian): one-minute cheat sheet, step-by-step defense script for the 4 procedure items, Q&A, what to do if a demo breaks |
| [`docs/lab4-guide.md`](docs/lab4-guide.md) | Lab 4 defense guide (Ukrainian): cheat sheet, defense script for the 4 procedure items, theory (stampede, avalanche, LRU / LFU, expiration vs invalidation) and Q&A, troubleshooting |
| [`docs/lab5-guide.md`](docs/lab5-guide.md) | Lab 5 defense guide (Ukrainian): cheat sheet, defense script for the 4 procedure items (k6 runs, analysis, scaling / cache comparison), theory (saturation point, coordinated omission, GC / JIT) and Q&A |
| [`docs/lab7-guide.md`](docs/lab7-guide.md) | Lab 7 defense guide (Ukrainian): cheat sheet, defense script for the 4 procedure items, theory (partitioning / sharding / replication, distributed JOIN, unique constraints, 2PC, Saga, consistent hashing), Q&A, troubleshooting |
| [`docs/lab6-guide.md`](docs/lab6-guide.md) | Lab 6 defense guide (Ukrainian): cheat sheet, defense script for the 4 procedure items, theory (replication modes, Split-Brain, CAP, PACELC, Raft), Q&A, troubleshooting |
| [`docs/about/lab2.md`](docs/about/lab2.md), [`lab3.md`](docs/about/lab3.md), [`lab4.md`](docs/about/lab4.md), [`lab5.md`](docs/about/lab5.md), [`lab6.md`](docs/about/lab6.md), [`lab7.md`](docs/about/lab7.md) | Pages to show the lecturer at the defense (Ukrainian): requirement → what was done → proof with numbers, diagrams, live-demo commands; no speaker notes |
| `docs/labs/*.md`, `docs/*.docx` | Original assignments / design docs (Ukrainian); summarized in `project-context.md` |

## Stack

C# / ASP.NET Core 10 (controllers) · EF Core 10 + Npgsql · PostgreSQL 17 · JWT · FluentValidation · Swashbuckle ·
Docker Compose. Redis since lab 2 (distributed results cache in lab 4), HAProxy since lab 3 (ADR 0031, instead of the
Nginx named in lab 1), k6 in lab 5, PostgreSQL streaming replica in lab 6 (ADR 0049), two shards with an application-level router in lab 7 (ADR 0055).

## Quick start

```bash
docker compose up -d --build     # lb (HAProxy) + backend-1/2 + postgres(+replica) = shard A + postgres-shard-b(+replica) = shard B + redis; migrations and seed run automatically
docker compose down -v           # wipe everything (cold start)
```

Web UI (React, `frontend/`) and API both through HAProxy http://localhost:8080 (backends publish no ports; stats http://localhost:8404/stats; one
instance directly: `docker-compose.debug.yml` → `127.0.0.1:8091–8093`) · Swagger `/swagger` · health `/health` ·
Postgres from host: Primary `localhost:5433`, Replica `localhost:5435` (`polling`/`polling`) · Redis `localhost:6379`.
Seed users: `user001@example.com` … `user500@example.com`, password `Password123!`. Details: `docs/ai/runbook.md`.

## Rules that must not be broken

- The whole stack must start with `docker compose up` and **no manual steps** (graded requirement).
- Schema changes only via EF migrations (`dotnet ef migrations add ...`); never manual SQL against the DB.
- Explicit DB transactions must run inside `db.Database.CreateExecutionStrategy().ExecuteAsync(...)` (the EF retry
  strategy is on — see ADR 0008). Otherwise EF throws at runtime.
- Follow the coding conventions in `src/PollingPlatform.Api/CLAUDE.md` so the codebase reads as one system.
- Don't make stateless/caching "improvements" ahead of the lab that asks for them: e.g. the results cache stayed in
  process memory until lab 2 moved it to Redis "as is" (ADR 0026), and its key schema, TTL, `X-Cache`, DB fallback
  and stampede protection came only with lab 4 (ADR 0041–0044); cache on/off comparisons and k6 wait for lab 5.
- Don't commit, push or create branches unless the user asks. No branching convention has been agreed yet.
- Never write personal names in repo files (code, docs, logs, ADRs, README): refer to people only as
  Participant 1 / Participant 2 (Учасник 1 / Учасник 2).
- No AI attribution anywhere: no `Co-Authored-By: Claude ...` trailers or "Generated with Claude Code" lines in
  commits/PRs, and no agent/model names as authors in code or docs. The participants are the authors.
- After changes, run the smoke test from the runbook against the Docker stack before reporting success.

## End of every session (mandatory)

1. **Log:** create `docs/ai/log/YYYY-MM-DD-p<1|2>-<short-topic>.md` (template below). One file per session — never
   append to someone else's log file (avoids merge conflicts).
2. **Status:** update `docs/ai/status.md` in place (it is a snapshot, not a history — rewrite outdated lines).
3. **Decisions:** for every non-obvious decision, add `docs/ai/decisions/NNNN-title.md` and a row in its README.
   If it replaces an older one, mark the old ADR `Superseded by NNNN` (don't delete it).
4. **Contracts/runbook:** update `contracts.md` / `runbook.md` if the API, schema, commands or setup changed.
5. **End of a lab:** write `docs/ai/labs/labN-summary.md` (what was built, final decisions, defense notes) so later
   sessions read one page instead of every log.
6. Keep this file short (~150 lines max) and limited to stable facts; details belong in `docs/ai/`.

Log template:

```markdown
# YYYY-MM-DD — Participant N — <topic>
**Lab:** N · **Commits:** <hashes or "not committed">
## Goal
## Done
## Decisions (link ADRs)
## Problems & fixes
## Verified (how)
## Not done / next steps
```
