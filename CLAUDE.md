# Polling Platform — High-Load Systems course project

Two-person university project for "High-Load Systems Engineering" (4th year). A real-time polling platform
(User, Poll, Option, Vote) that grows over 5 labs: MVP → stateless → horizontal scaling → distributed caching →
load testing. **Participant 1** ("platform": infra, DB, auth, poll lifecycle);
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
| [`docs/ai/project-context.md`](docs/ai/project-context.md) | You need lab requirements, the design-doc summary, the high-load scenario, bottlenecks, defense questions |
| [`docs/ai/contracts.md`](docs/ai/contracts.md) | You touch the API, DB schema, or code another participant depends on; open questions for Participant 2 |
| [`docs/ai/runbook.md`](docs/ai/runbook.md) | Running, testing, migrations, seed data, troubleshooting |
| [`docs/ai/decisions/`](docs/ai/decisions/README.md) | Before changing an established approach (why things are the way they are) |
| [`docs/ai/log/`](docs/ai/log/) | You need the history of a specific session (normally not needed) |
| [`docs/ai/labs/`](docs/ai/labs/) | Summaries of finished labs |
| `src/PollingPlatform.Api/CLAUDE.md` | Auto-loaded when working in the code: structure and coding conventions |
| `docs/labs/*.md`, `docs/*.docx` | Original assignments / design docs (Ukrainian); summarized in `project-context.md` |

## Stack

C# / ASP.NET Core 10 (controllers) · EF Core 10 + Npgsql · PostgreSQL 17 · JWT · FluentValidation · Swashbuckle ·
Docker Compose. Redis arrives in labs 2/4, Nginx in lab 3, k6 in lab 5.

## Quick start

```bash
docker compose up -d --build     # backend + postgres; migrations and seed run automatically
docker compose down -v           # wipe everything (cold start)
```

API http://localhost:8080 · Swagger `/swagger` · health `/health` · Postgres from host `localhost:5433` (`polling`/`polling`).
Seed users: `user001@example.com` … `user500@example.com`, password `Password123!`. Details: `docs/ai/runbook.md`.

## Rules that must not be broken

- The whole stack must start with `docker compose up` and **no manual steps** (graded requirement).
- Schema changes only via EF migrations (`dotnet ef migrations add ...`); never manual SQL against the DB.
- Explicit DB transactions must run inside `db.Database.CreateExecutionStrategy().ExecuteAsync(...)` (the EF retry
  strategy is on — see ADR 0008). Otherwise EF throws at runtime.
- Follow the coding conventions in `src/PollingPlatform.Api/CLAUDE.md` so the codebase reads as one system.
- Don't make stateless/caching "improvements" ahead of the lab that asks for them: e.g. the lab 1 results cache is
  **deliberately** in process memory — it is the lab 2 state-audit target.
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
