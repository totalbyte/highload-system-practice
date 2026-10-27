# 2026-10-27 — Participant 1 — Lab 2 task split + П1-1…П1-7 (Redis, two instances, concurrent startup, DataProtection, platform audit, cross-instance chain, C4)
**Lab:** 2 · **Commits:** `320ca8e` (task split, on `main`); `c6f81ac` (П1-1, П1-2) merged via PR #2 as `78128e9`; П1-3 `17bbae3` on `lab2/p1-platform`; П1-4 `4d877a4`; П1-5 `9c2c8d2`; П1-6 `f1a4525`; П1-7 (docs only) not committed

## Goal
Read the lab 2 assignment and the repository, split lab 2 between the two participants so both can work in parallel
in their own branches, and estimate the AI-assisted chat time.

## Done
- Compared the lab 2 `.docx` with `docs/labs/Lab2 - Stateless Architecture.md` — identical text.
- Scanned the code for in-process state: `ResultsCache` (`IMemoryCache` singleton) and file-based DataProtection keys
  are the critical items; JWT, the advisory-locked seed, `vote_count` and the vote locks are already shared (DB);
  the remaining singletons/statics hold no data. ADR 0009 (concurrent `MigrateAsync`) is still unverified.
- Wrote `docs/lab2/participant-1.md` and `docs/lab2/participant-2.md` (Ukrainian): tasks П1-1…П1-7, П2-1…П2-8,
  joint С-1…С-6, each with the lab clause it covers, done criteria and time; plus identical shared sections
  (parallel-work rules, lab 2 scope limits, order of work, lab-requirement coverage matrix, defense theory).
  Checked that the shared sections are byte-identical in both files.
- Rewrote `status.md` for lab 2 (one table per participant to avoid merge conflicts); noted that PR #1 is merged.

## Decisions (link ADRs)
No ADRs — the proposals below are not yet confirmed by Participant 2 (task С-1):
- Redis arrives in lab 2, but the results cache moves there "as is" (same key, 10 s TTL, same invalidation);
  key schema, `X-Cache`, fallback, stampede protection and cold/hot latency stay in lab 4.
- No load balancer in lab 2: `backend-1` on 8080, `backend-2` on 8082 (8081 is Adminer), `INSTANCE_ID=backend-1/2`.
- Branches `lab2/p1-infra` (merged first), `lab2/p1-platform`, `lab2/p2-voting`; ADR ranges 0021–0025 / 0026–0030.
- Participant 1 registers one `IConnectionMultiplexer`; Participant 2 adds no NuGet packages (no `.csproj` conflict).
- The cross-instance chain (lab 2.5, first bullet) is owned by Participant 1 and covers polls, votes and results;
  the instance-loss test (second bullet) by Participant 2.

## Problems & fixes
- The lab 2 `.docx` was read with Python `zipfile` (no `python-docx` / `pandoc` on this machine).

## Verified (how)
- Shared sections of the two task files compared with `awk` + `cmp` — identical; every lab 2 requirement (2.1–2.6,
  §3, §4) maps to at least one task in the coverage matrix.
- No code changed, so the smoke test was not run.

## П1-1: Redis and two backend instances (branch `lab2/p1-infra`)
- `docker-compose.yml`: `backend-1` / `backend-2` from one `x-backend` anchor (one image, `INSTANCE_ID`, ports
  8080 / 8082), Redis `redis:8.10.2-alpine` with healthcheck and host port 6379; backends wait for postgres and redis.
- `Program.cs`: one `IConnectionMultiplexer` singleton (`StackExchange.Redis` 3.4.20), `ConnectionStrings:Redis` with
  `abortConnect=false`; nothing uses Redis yet — the results cache stays in memory for Participant 2's "before" demo.
- `.env.example` (`API2_PORT`, `REDIS_PORT`), README quick start + lab 2 section skeleton with an owner per
  subsection, runbook, contracts, `src/.../CLAUDE.md`, ADR 0021 (also: `/health` does not check Redis in lab 2).
- No comment added to `docker-compose.yml` — comments were deliberately removed from it in `dd8d19e`.
- Verified: `docker compose down -v && up -d --build` → both healthy within ~2 s of `up` returning, `X-Instance-ID`
  `backend-1` / `backend-2`, both containers run the same image id, Redis `PONG` and two client connections per
  instance; runbook smoke test (scripted, 11 checks) passed on 8080 and 8082; after `restart postgres` both return
  200; per-option counter query → 0. The simultaneous cold start applied the migration once (1 history row) and
  seeded once (500 / 50); the `__EFMigrationsHistory` "Failed executing DbCommand" on first start is the known quirk.

## П1-2: concurrent startup on an empty DB (ADR 0022, amends 0009)
- 12 cold starts of both instances at once (7 with PostgreSQL `log_statement=all` via a temporary override file in the
  scratchpad, not in the repo): every run healthy, no restarts, one `__EFMigrationsHistory` row, seed applied once.
- The statement log shows why: the Npgsql provider wraps migrations in `LOCK TABLE "__EFMigrationsHistory" IN ACCESS
  EXCLUSIVE MODE`, the seed takes our `pg_advisory_xact_lock`.
- Captured a rare harmless race (2/12): concurrent `CREATE TABLE IF NOT EXISTS "__EFMigrationsHistory"` →
  `23505 pg_type_typname_nsp_index`; the provider rolls back and continues to `LOCK TABLE`. Added to runbook quirks.
- No `migrator` service needed. ADR 0009 status → "amended by 0022"; `DatabaseInitializer` comment updated.
- After the comment change: rebuild + cold start, smoke test 11/11 on 8080 and 8082.

## PR #2
- Opened by Participant 1, merged 2026-10-27 (`78128e9`) together with Participant 2's `10fe4fd` (lab 1 guide, docs
  only, no conflicts). The only failing check was GitGuardian: it flagged the local-dev default DB password `polling`
  on the compose line that moved into the YAML anchor — present in `main` since lab 1, a false positive; no history
  rewrite.

## П1-3: DataProtection keys in Redis (ADR 0023, branch `lab2/p1-platform`)
- `Program.cs`: `AddDataProtection().SetApplicationName("polling-platform").PersistKeysToStackExchangeRedis(redis,
  "DataProtection-Keys")` with the shared multiplexer; package `Microsoft.AspNetCore.DataProtection.StackExchangeRedis`
  10.0.12. Placed next to the Redis registration, away from the cache lines Participant 2 edits.
- Verified: cold start → one key in Redis created by `backend-2`, `backend-1` used it (no key-creation warning of its
  own); the "not persisted outside of the container" warning is gone; after `docker compose rm -sf backend-1
  backend-2 && up -d` still one key and no DataProtection warnings; smoke test 11/11 on 8080 and 8082.
- README "Усунені in-memory залежності": before/after table for DataProtection; runbook quirk row replaced.

## П1-4: platform state audit (README, subsection "Платформа")
- Grepped `Program.cs`, `Auth/`, `Polls/`, `Data/`, `Common/` (without error handling) for `static`, singletons,
  collections, locks, timers, hosted services, file/directory access, sessions: only immutable config/handlers,
  `static readonly` seed topics, per-request objects — no background jobs, in-process locks or data in memory.
- README table: 13 elements in the lab's three categories; DataProtection keys shown as Critical → Shared.
- No-sessions proof on the running stack: register on `backend-2` → login on `backend-1` (no `Set-Cookie`) → `/me`
  with that token 200 on both; tampered token → 401; `Jwt__Secret` hash identical in both containers.
- Hidden-affinity demo for the defense: temporary `docker compose run` instance on :8083 with another `Jwt__Secret`
  → `401 invalid_token ... signature key was not found` for a token from `backend-1`; container stopped afterwards.

## П1-5: cross-instance consistency chain
- First version had 14 steps / 21 automated checks (delete and duplicate-vote steps, assertions, exit code).
  Participant 1 asked not to over-engineer beyond the lab, so it was cut to the lab's chain plus the results steps.
- `scripts/cross-instance.sh`: 8 plain curl steps alternating instances, each prints `X-Instance-ID`, HTTP code and
  one key field; `requests/cross-instance.http` — the same steps for REST Client.
- Current output: steps 1–7 consistent, step 8 `totalVotes: 0` instead of 1 — `backend-2` serves the copy it cached
  in step 6 (in-memory cache, up to the 10 s TTL). Expected until Participant 2's П2-3.
- README section and `docs/lab2/participant-1.md` (П1-5) updated to the 8-step version.

## П1-6: C4 component diagram and deployment docs (README)
- "Архітектура (Lab 1)" replaced by "Архітектура (Lab 2)": mermaid flowchart at C4 component level — `backend-1`
  with its components (JWT/X-Instance-ID middleware, controllers, services, `ResultsCache`, `AppDbContext`,
  DataProtection, `/health`), `backend-2` as the same image, PostgreSQL and Redis with what each stores. Shows the
  lab 2 target state; a note says the cache moves to Redis in П2-3. Rendered with mermaid 11.4.1 in a browser to
  check the syntax (scratch page, not in the repo).
- "Мульти-інстансне розгортання": one-command start, instance/port table, `X-Instance-ID` check, per-instance
  stop/kill/start/logs, `redis-cli`. RACI: lab 2 rows; repo structure: `scripts/`. Runbook/contracts were already
  updated in П1-1.

## П1-6 review and П1-7
- Review of П1-6 against lab 2.6 and §3: diagram matches the code; the documented stop/kill/start/`redis-cli`
  commands were run on the stack. Finding: after `docker compose kill` the container stays `Exited (137)` — the
  restart policy does not apply to a manual kill, so `start` is required (comment added; relevant to П2-7).
- П1-7: cold start → smoke test 11/11 on 8080 and 8082, both 200 after `restart postgres`, per-option counters 0
  mismatches, no "not persisted outside of the container" warning. All Participant 1 README placeholders are filled;
  the remaining four belong to Participant 2.

## Merging lab 2 into main
- Before the PRs: trial merge of `lab2/p1-platform` and `lab2/p2-voting` in a scratch worktree — code merged
  cleanly, 3 doc conflicts (README structure lines, ADR index, status "Next steps"); on the merged code all checks
  passed, step 8 of the chain = 1. Worktree removed afterwards.
- PR #4 (`lab2/p1-platform`) merged first (`7d6ede8`); Participant 2 merged `main` into `lab2/p2-voting`, resolved
  the 3 conflicts as agreed (checked: no markers, ADR index 0020–0023, 0026, 0027) and PR #3 was merged (`288534e`).
- On `main`, cold start: smoke 11/11 on both instances, `cross-instance.sh` 8/8, Participant 2's four scripts passed.
- README: removed the "target state, cache moves in П2-3" note under the C4 diagram; replaced the stale chain output
  with the current one (step 8 `totalVotes: 1`).

## Not done / next steps
- Joint tasks: С-3 consolidated audit table, С-4 code audit (Participant 1 leads), С-5 cold-start rehearsal,
  С-6 `docs/ai/labs/lab2-summary.md`.
