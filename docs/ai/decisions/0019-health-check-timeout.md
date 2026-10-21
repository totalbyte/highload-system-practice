# 0019. `/health` uses its own PostgreSQL probe with a 2 s timeout
**Status:** Accepted (amends 0012) · **Date:** 2026-09-30 · **Author:** Participant 1

## Context
The review (`log/2026-09-22-p1-lab1-review.md`, problem 4) measured `/health` at ~16 s when the DB container was
stopped: `AddDbContextCheck` goes through the EF retry strategy (ADR 0008). A load balancer (lab 3) needs an answer in
1–2 s. While fixing it two more facts came up:
- A plain 2 s `HealthCheckRegistration.Timeout` only brought it down to ~3.3 s: resolving the name of a **stopped**
  container through Docker's DNS takes ~3.3 s (`getent hosts postgres` → not found after 3.3 s) and that lookup
  ignores the cancellation token.
- Abandoning the DbContext check with `WaitAsync` made it worse: the scoped DbContext was disposed while its
  connection was still `Connecting`, Npgsql threw `Can't close, connection is in state Connecting` → **500**.

## Decision
- `Common/PostgresHealthCheck.cs`: a small `IHealthCheck` that opens its own `NpgsqlConnection` (same connection
  string and pool as EF, but no DbContext and no retry strategy) and runs `SELECT 1`.
- Registered with a 2 s timeout, configurable as `HealthChecks:DbTimeoutSeconds` (`appsettings.json`, env
  `HealthChecks__DbTimeoutSeconds`); the probe is awaited with `WaitAsync(token)`, so the check returns at the timeout
  even when DNS hangs. The abandoned probe finishes in the background and disposes its own connection.
- A timeout returns `Unhealthy` with the message "PostgreSQL did not respond within the timeout" (no stack trace in
  the logs — the LB will poll this endpoint every few seconds while the DB is down).
- The `Microsoft.Extensions.Diagnostics.HealthChecks.EntityFrameworkCore` package was removed (no longer used).

## Consequences
- Verified 2026-09-30: DB up → 200 in ~1 ms; DB container stopped → 503 in 2.0 s (the very first request after the
  stop fails in ~25 ms, when the pooled connection is already broken); DB started again → 200; no errors in logs.
- Regular API requests are unchanged when the DB is down: ~13–16 s of EF retries (+ slow DNS) and then 503
  (ADR 0016). That is the retry strategy doing its job; the LB decides by `/health`, not by those requests.
