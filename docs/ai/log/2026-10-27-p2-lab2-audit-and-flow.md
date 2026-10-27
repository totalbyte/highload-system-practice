# 2026-10-27 — Participant 2 — lab 2: state audit (П2-1), stateless request flow (П2-5), "before" demo (П2-2), cache in Redis (П2-3)
**Lab:** 2 · **Commits:** on branch `lab2/p2-voting` — `e92f372` (drafts), `e5c3431` (drafts → README), `f75eea5` (П2-2),
then П2-3; lab 1 guide separately on `main` as `10fe4fd`

## Goal
Pull the lab 2 task split and Participant 1's review fixes, then start the Participant 2 tasks that do not depend on
the `lab2/p1-infra` branch (Redis + two instances): П2-1 and П2-5.

## Done
- Local `main` was 9 commits behind `origin/main` and the pull clashed with uncommitted lab 1 edits (guide links in
  `README.md` / `CLAUDE.md`, a log line). Stashed them (`-u`), fast-forwarded, popped — merged cleanly, nothing
  duplicated. They are still uncommitted and travel with the working copy onto `lab2/p2-voting`.
- Created the local branch `lab2/p2-voting` from the fresh `main` (proposed convention, not yet confirmed — С-1).
- **П2-1:** state audit of `Votes/`, `Results/`, `Common/ErrorHandling/`, `VoteExceptions.cs` and their DI
  registrations, done against the code (grep for `static`, locks, `Concurrent*`, `IMemoryCache`, timers, files,
  sessions; review of every registration lifetime) — not copied from the indicative table in `participant-2.md`.
- **П2-5:** stateless request flow for `POST /vote`: the four 2.3 requirements mapped to the code, a mermaid sequence
  diagram (target state after П2-3), the per-option invariant, and what happens if an instance dies mid-request.
- Both drafts were first kept in `docs/lab2/p2-readme-drafts.md` (commit `e92f372`), because the lab 2 README
  skeleton was still to come with П1-1. After `lab2/p1-infra` was merged (PR #2), `main` was merged into
  `lab2/p2-voting` (no conflicts), both drafts moved into the README skeleton («Аудит стану → Голосування й
  результати», «Stateless Request Flow») and the drafts file was deleted.
- README bottleneck #2 no longer says the cache moves to Redis "in lab 4" — it moves in lab 2 (П2-3); lab 4 is
  Cache-Aside, key schema, TTL rationale and DB fallback (as Participant 1 pointed out).

- **П2-2 (the "before" demo):** `scripts/results-cache-demo.py` — Python stdlib only, fresh polls per run, so it is
  repeatable and will be re-run unchanged after П2-3 as the "after". Scenario A: warm the cache on backend-2, vote via
  backend-1 → backend-2 keeps `totalVotes=0` with the same `generatedAt` until the TTL. Scenario B: the author previews
  a draft on backend-2, publishes via backend-1 → backend-2 answers **404** to others while backend-1 answers 200.
  Stable in 3 consecutive runs; output and explanation in README «Усунені in-memory залежності → Кеш результатів».
  Runbook: how to run it, expected before/after summary.
- Cold start for the demo: `docker compose down -v` + `up -d --build`. Host port 5433 was held by `kafka-sandbox-db-1`
  (an unrelated project, auto-started by Docker Desktop) → local gitignored `.env` with `POSTGRES_PORT=5434`; the
  team default is unchanged. Recorded in runbook troubleshooting and Participant 2's environment. Seed ran once on
  the concurrent start: 500 users, 50 polls, 0 per-option counter mismatches.

- **П2-3 (cache → Redis):** `ResultsCache` rewritten on the shared `IConnectionMultiplexer` (`IDatabase`, no new
  packages): `GetAsync` / `SetAsync` (JSON, `SET … EX 10`) / `InvalidateAsync` (`DEL`); callers updated in
  `ResultsService`, `VoteService` and the three invalidation points in `PollService` (publish/close/delete — only those
  lines in Participant 1's file); `AddMemoryCache()` removed. StackExchange.Redis is **3.x**: TTL goes through the
  `Expiration` type (checked against the package's XML docs, not from memory). Docs: README «Після» with the real
  output, the Request Flow note, structure and bottleneck #2; ADR 0013 → superseded; contracts (new API + Redis
  format); runbook; both `CLAUDE.md` files; `project-context.md`.

## Decisions (link ADRs)
- [0026](../decisions/0026-results-cache-in-redis.md) — results cache in Redis as is (key, JSON, TTL 10 s, `DEL`),
  async API; supersedes 0013. Enum stored as a camelCase string so the value is readable in `redis-cli`.

## Problems & fixes
Audit findings missing from the indicative table, recorded in the drafts file:
1. The cached entry holds the poll `Status`, so across instances not only the numbers go stale — after a publish on
   one instance the other keeps answering **404** to non-authors for up to 10 s. Better hidden-affinity demo for П2-2.
2. `GlobalExceptionHandler` is a **singleton** (`AddExceptionHandler`), not scoped — safe (no mutable fields), but
   С-4's grep will flag it.
3. The read-before-commit / cache-after-invalidation race stays after the move to Redis (lab 4 topic).
4. A commit whose acknowledgement is lost is retried (EF strategy or client on the other instance) and answered 409 —
   stored exactly once; expected behaviour for П2-7.

Lab 1 leftover, fixed: `docs/lab1-guide.md` claimed the 40-vote check proved "no lost updates", but ADR 0017 showed
the vote-change race that check missed (it compared SUMs). The guide was brought in line with all review fixes
(ADR 0017–0019, invalidation on publish/close/delete, pgAdmin, per-option check) and committed **separately to
`main`** as `10fe4fd` together with the guide links and the README bottleneck #2 wording; `lab2/p2-voting` was
fast-forwarded onto it, so the lab 2 PR stays free of lab 1 changes.

## Verified (how)
П2-3, on the stack rebuilt with `docker compose up -d --build`: `dotnet build` clean; `results-cache-demo.py` →
«no» / «no» in 3 runs; `TTL results:1` = 9 after a read, `EXISTS` = 0 after a vote; response format unchanged
(`status` as `"active"`, `generatedAt`, percentages). Parallel checks split across backend-1/backend-2: 120 first
votes → all 201 and identical results on both; 40 changes by one user → all 200, total 1; 100 opposite changes → all
200, 50/50; per-option counter mismatches 0; no deadlocks or `fail:` entries in the logs. Runbook smoke test (create
201, list 200, no token 401, DB restart → 200 on both instances).

Earlier in the session (П2-1, П2-5 drafts):
Documentation only, no code changed — no build or smoke test needed. Every claim in the audit and the flow was
checked against the current `VoteService.cs`, `ResultsService.cs`, `ResultsCache.cs`, `PollService.cs`,
`GlobalExceptionHandler.cs` and `Program.cs` on `origin/main` `320ca8e`.

## Not done / next steps
- П2-4: Redis down → 503 instead of 500; a vote already committed must not be reported as failed when only the
  invalidation fails (ADR in the 0026–0030 range).
- П2-6 (the three concurrency checks across two instances as a script in `scripts/`), П2-7 (instance-loss test),
  П2-8 (remaining README sections, runbook).
- С-1: confirm the proposals in `docs/lab2/participant-*.md` with Participant 1; С-2: Participant 1 reviews the three
  `InvalidateAsync` lines in `PollService`.
