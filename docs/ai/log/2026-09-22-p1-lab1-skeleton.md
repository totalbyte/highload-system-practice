# 2026-09-22 — Participant 1 — Lab 1 skeleton, DB, auth, poll CRUD, agent docs
**Lab:** 1 · **Commits:** not committed (all changes in Participant 1's working directory)

## Goal
Understand the course documents, determine Participant 1's scope (lab 1 stages 1–4) and implement it; set up
documentation so Participant 2 and their Claude agent can continue.

## Done
1. **Analysis:** read `docs/labs/*.md` and the three team `.docx` files. Gaps found in the design: no draft → active
   transition; `register/login` missing from the endpoint list; a Word lock file in the repo.
2. **Decisions with Participant 1:** stack C# / ASP.NET Core (ADR 0001); `PATCH /publish` for draft → active (ADR 0002).
3. **Project:** `PollingPlatform.sln`, `src/PollingPlatform.Api` (`dotnet new webapi --use-controllers`, net10.0),
   template removed. Packages: Npgsql EF, EFCore.NamingConventions, EF Design, JwtBearer,
   HealthChecks.EntityFrameworkCore, FluentValidation (+DI), Swashbuckle.
4. **DB:** entities, Fluent configurations, migration `InitialSchema` (generated SQL reviewed) — ADR 0007.
5. **Auth:** register / login / me, JWT, PBKDF2 — ADR 0006.
6. **Polls:** create / list / get / publish / close / delete with validation, visibility rules, atomic transitions —
   ADRs 0002–0004.
7. **Shared:** `AppException` hierarchy + `GlobalExceptionHandler` (ADR 0005), `ValidateOrThrowAsync`,
   `X-Instance-ID`, `/health` (ADR 0012).
8. **Seed + startup:** deterministic seed under an advisory lock, migrations + seed on startup — ADRs 0009, 0010.
9. **Docker:** `Dockerfile`, `docker-compose.yml` (backend, postgres with healthcheck, adminer under profile
   `tools`), `.env.example`, `.dockerignore`, `.gitignore` (incl. `~$*` Word lock files).
10. **Docs:** `requests/polls.http`, `README.md` (run, API, ER diagram, architecture, RACI, structure); replaced every
    "тбд" in `docs/Lab1 - System Design (Платформа опитувань).docx` with the stack, repo URL and Swagger URL (text
    edited in `word/document.xml`, formatting preserved).
11. **Agent docs:** first as a single `docs/CLAUDE.md`, translated to English at Participant 1's request, reviewed for
    cold-start sufficiency, then — because a single growing file would bloat every session's context and cause merge
    conflicts — split into: root `CLAUDE.md` (short, always loaded), `src/PollingPlatform.Api/CLAUDE.md` (code
    conventions, loaded when working in code), `docs/ai/{status,project-context,contracts,runbook}.md`,
    `docs/ai/decisions/` (13 ADRs), `docs/ai/log/` (one file per session), `docs/ai/labs/` (per-lab summaries).
    `docs/CLAUDE.md` was removed.

## Problems & fixes
- Seed produced closed polls with `ends_at < starts_at` (CHECK violation) → `ends_at = created_at + 1..19 h`.
- First request after a Postgres restart returned 500 (dead pooled connections) → EF retry strategy + execution
  strategy in the seeder (ADR 0008).
- Host port 5432 taken by a local Windows PostgreSQL → container published on 5433; `libgssapi_krb5` log noise →
  `Gss Encryption Mode=Disable` (ADR 0011).
- `UpdateSettersBuilder` lives in `Microsoft.EntityFrameworkCore.Query` (EF Core 10) — missing using caused a build
  error.
- `????` instead of Cyrillic in one test was caused by curl in Git Bash on Windows, not the server (checked in psql).

## Verified (how)
Live against the Docker stack: cold start `down -v` → `up` ≈ 13 s to healthy; seed 500 users / 50 polls / 4953
votes with `SUM(vote_count) = COUNT(votes)`; every endpoint and status code 201/200/204/400/401/403/404/409/422
(curl script); data survives `restart postgres` with no 500s; backend restart skips the seed; an old JWT stays valid
after a backend restart; Swagger lists 7 paths; 401 responses carry a ProblemDetails body.

## Not done / next steps
- Commit and push (awaiting Participant 1); agree on a branching convention.
- Stages 5–8 — Participant 2 (see `docs/ai/contracts.md`, including open questions).
- Full C4 diagram (stage 9); no automated tests.
- Unverified: concurrent migrations with two instances (ADR 0009) — lab 2.
