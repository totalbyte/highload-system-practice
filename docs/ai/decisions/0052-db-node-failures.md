# 0052. Lab 6: database node failures: monitor, Primary Fallback, Read-Only Mode
**Status:** Accepted (amends 0019, 0033, 0051) · **Date:** 2026-11-08 · **Author:** Participant 1

## Context
Lab 6 (2.5) asks for graceful degradation in both directions. Measured before this change: with the replica stopped, catalog reads
answered 503 after 8.6–10.6 s. Without the Primary, requests wait 13–19 s of EF retries (ADR 0019), and `/health` checked only the
Primary, so HAProxy would take every backend out and reads from the live replica would die with the writes.

Npgsql's multi-host connection strings could cover the read fallback, but not the fast rejection of writes, and they would hide from
the application which node answered. So one small monitor was built instead, as the plan required after measuring.

## Decision
- **`DbNodeMonitor`** (`BackgroundService`, one per instance, state is derived and short-lived): `SELECT 1` on each node every 1 s, with its
  own unpooled connection and a 2 s timeout. Unpooled on purpose: under load the shared pool is busy and a queued probe would declare a
  healthy Primary dead at the peak. Two failures in a row mark a node down, one success brings it back. "Too many clients" counts as alive.
- **Passive signal:** a live request that fails to connect marks the node down at once (`DbNodeGuardInterceptor.ConnectionFailed`), because
  the active check alone left a ≈ 5 s window with every read waiting ≈ 2.3 s. Timeouts do not count, since a busy pool looks the same.
- **Replica lost, Primary Fallback:** `ReadDb` sends reads to the Primary. A read that fails meanwhile is repeated on the other node.
  That is why reads are passed as a function (`EventualAsync`, replaces `ForEventualReadAsync` from ADR 0051), and why the replica context has
  no EF retries.
- **Primary lost, Read-Only Mode:** the interceptor refuses to open a Primary connection and throws `ReadOnlyModeException` → 503 ProblemDetails
  with the title `Read-Only Mode`. One place covers every write and strict read. Eventual reads stay on the replica, and sticky users read the
  replica too, because stale data beats an error when nothing can be written.
- **Results during a Primary outage:** a MISS / BYPASS reads the replica, but **only Primary data goes into the cache** (the experiment in ADR 0051
  showed why). If the monitor is wrong and votes still commit, a replica aggregate cannot poison the cache.
- **`/health`** answers from the monitor's state at once: `Healthy` both up, `Degraded` (200) one down, with `detail`; `Unhealthy` (503) both down.
  It replaces `PostgresHealthCheck`. HAProxy keeps a backend while any database node lives. The contract of ADR 0019 (never through EF, fast) still holds.
- **No automatic promotion** (ADR 0049): writes come back when the Primary does.

## Consequences
- Verified 2026-11-08, `scripts/db-failure-check.py`, 2 runs, ALL PASSED, 4 readers in the background:
  - Replica stop: 768 and 807 reads, **0 errors**, slowest 152 and 39 ms; writes 201; `/health` 200 Degraded; back on the replica in 0.7–1.3 s.
  - Primary stop: 1581 and 1120 catalog reads, **0 errors**, slowest 34 ms; details and results 200 from the replica; create, vote, login, `/me`: 503
    `Read-Only Mode` in 9–87 ms; writes back in 1.7–2.3 s, WAL streaming in 0.3–0.8 s, no backend restart.
  - Both stopped: `/health` 503 after 4.4–4.7 s; back in 1.2–1.3 s.
- No false failover: `load.py` write (64 threads, 20 s) and read (64 threads, 10 s) gave 0 node state changes. The full load series is stage 5.
- **Known window:** the first write right after the Primary stops waits 4.3–8.1 s (EF retry and DNS of a stopped container) before its 503; later ones take
  milliseconds. A vote in flight at that moment may have committed before the crash, and the client sees 503: the retry then gets 409 or 200 (ADR 0037).
- A backend cannot **start** without the Primary (migrations and seed run on startup; it restarts until the Primary is back). Instances already running keep serving.
- `login` is a strict read, so new sessions cannot start during the outage. Existing JWTs still work for catalog reads, which need no database check of the user.
- EF still logs its own `fail:` lines (`Database.Connection`, `Update`) for refused requests during an outage. Only the application's handler is quiet.
- Each backend opens 2 short connections per second for the probes: visible in `xact_commit`, small against the load, identical in the compared configurations.
- A replica that is far behind counts as healthy: routing does not look at lag. The sticky TTL (ADR 0051) is the only protection, and only for the writer.
