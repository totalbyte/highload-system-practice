# 2026-09-30 — Participant 1 — fixes for the stage 5–8 review findings
**Lab:** 1 · **Commits:** `8a2c1e1` (fixes) + a separate pgAdmin commit, both on branch `fix/lab1-review-findings`

## Goal
Fix problems 1–4 from `log/2026-09-22-p1-lab1-review.md`, re-verify the whole system, and record the changes in the
existing docs. Problem 1 is in Participant 2's module (`VoteService`); Participant 1 fixed it with the team's consent.

## Done
1. **Vote-change race** (`Votes/VoteService.cs`): the existing vote is read with
   `db.Votes.FromSql($"SELECT * FROM votes WHERE poll_id = … AND user_id = … FOR UPDATE")` (composed with the
   existing projection); when a vote moves, the two `options` rows are updated in ascending id order. — ADR 0017.
2. **Stale cache after publish/delete** (`Polls/PollService.cs`): `resultsCache.Invalidate(pollId)` in
   `PublishAsync` and `DeleteAsync` (close already had it).
3. **Connection budget**: `Maximum Pool Size=${DB_MAX_POOL_SIZE:-30}` in the compose connection string, `30` in
   `appsettings.json`, `DB_MAX_POOL_SIZE` documented in `.env.example`. — ADR 0018.
4. **`/health` timeout**: new `Common/PostgresHealthCheck.cs` (own `NpgsqlConnection` + `SELECT 1`, awaited with
   `WaitAsync`, timeout → Unhealthy without a stack trace) registered in `Program.cs` with a 2 s timeout; the connection
   string is now read once into `postgresConnectionString`; the unused package
   `Microsoft.Extensions.Diagnostics.HealthChecks.EntityFrameworkCore` was removed. — ADR 0019.
5. **Local data repair**: the counters of poll #1 skewed by the 2026-09-22 race test were recomputed from `votes`
   (`UPDATE options … SET vote_count = (SELECT count(*) …)`, 4 rows) — data only, no schema change.
6. **Docs**: ADRs 0017–0019 (+ index; 0012 and 0014 marked "amended by"), README bottlenecks #1 and #3 (the old
   "no lost updates, verified by SUM" claim corrected), `contracts.md` (health timing, same-user serialization, full
   list of invalidation points), `runbook.md` (per-option counter query, three concurrency checks, pool budget, new
   troubleshooting rows, cold-start time), `project-context.md` (lab 2–4 groundwork: connection budget, LB check
   timeout, finding 5 parked for lab 4), `src/PollingPlatform.Api/CLAUDE.md` (structure + behaviour to preserve),
   `status.md`.

## Decisions (link ADRs)
- [0017](../decisions/0017-serialize-vote-changes.md) — `FOR UPDATE` on the vote row + ascending lock order for
  option rows. Chosen over a conditional `UPDATE … WHERE option_id = @old` with a retry loop: simpler, and the lock is
  per user per poll, so it adds no contention between different voters.
- [0018](../decisions/0018-connection-pool-budget.md) — pool 30 per instance; instances × pool ≤ 97.
- [0019](../decisions/0019-health-check-timeout.md) — own probe + 2 s timeout instead of `AddDbContextCheck`.
- Review finding 5 (stale results cached right after an invalidation, ≤ 10 s) deliberately **not** fixed: acceptable
  for lab 1, parked as a lab 4 discussion point in `project-context.md`.

## Problems & fixes
- A 2 s `HealthCheckRegistration.Timeout` alone gave ~3.3 s: Docker's DNS takes ~3.3 s to answer "not found" for the
  name of a stopped container (`getent hosts postgres` inside the backend container), and that lookup ignores the
  token. Wrapping the DbContext check in `WaitAsync` then produced **500**: the scoped DbContext was disposed while its
  connection was still `Connecting` (`Can't close, connection is in state Connecting`). Solved by probing with a plain
  `NpgsqlConnection` outside the DbContext (ADR 0019).
- The framework logged each health-check timeout as "threw an unhandled exception" with a stack trace — noisy under
  LB polling; the probe now catches the timeout and returns Unhealthy with a one-line message.

## Verified (how)
- `dotnet build`: 0 warnings, 0 errors; stack rebuilt with `docker compose up -d --build`.
- A 48-check Python script (parallel HTTP via `ThreadPoolExecutor`, SQL via `docker compose exec postgres psql`):
  regression of all endpoints and error codes, cache invalidation incl. **publish** (others get 200, not 404) and
  **delete** (404, not cached results), time window, vote change; concurrency: 200 users voting at once, 40 parallel
  changes by one user on a fresh poll **and** on poll #1 (all 200, per-option counters exact, one vote row),
  100 users making opposite changes at once (all 200, 50/50, no deadlocks in logs); pool: backend held 30
  connections afterwards and `psql` connected; global per-option invariant = 0 mismatches. **48/48** on the running
  stack, and **48/48** on a cold start in an isolated compose project (`-p pp-coldcheck`, ports 18080/15433, healthy in
  11 s, 200× 201 for first votes; removed afterwards).
- `/health`: DB up → 200 in ~1–8 ms; DB container stopped → 503 in 2.0 s (first request ~25 ms); DB started → 200;
  no error entries in the backend log.
- DB restart → `GET /api/polls/1` 200.

## Later in the same session: pgAdmin 4
At Participant 1's request, in a separate commit: `pgadmin` service in `docker-compose.yml` (profile `tools`,
image pinned to `dpage/pgadmin4:9.17.0` — pgAdmin has no LTS line, so an exact tag one release behind the newest
`9.18.0`), desktop mode without login, server pre-registered (first from `docker/pgadmin/servers.json`; on Participant 1's request that folder was then
replaced by an inline Compose `configs` entry with `${POSTGRES_DB}`/`${POSTGRES_USER}` substitution, in a separate
commit), volume
`pgadmin-data`, port 5050; `.env.example`, README, runbook updated — ADR [0020](../decisions/0020-pgadmin-pinned.md).
Verified: UI answers on :5050 after ~40 s, logs show "Added 1 Server(s)", `psql` from the pgAdmin container reaches
PostgreSQL 17.11.

Code comments added during the fixes were removed at Participant 1's request (the reasoning lives in ADRs 0017–0019).
The fixes were first committed on `main`, then moved to the new branch `fix/lab1-review-findings`; local `main` was
reset to `origin/main` (nothing had been pushed).

## Not done / next steps
- Participant 1 pushes `fix/lab1-review-findings` and opens a PR; agree on a branching convention.
- Participant 2 should read ADR 0017 (their module changed).
- Stage 10 — defense rehearsal together.
- The verification script lives only in Participant 1's temp folder; the checks it runs are described in
  `runbook.md` ("Concurrency checks"). Adding it to the repo is an open option.
