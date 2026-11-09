# 0051. Lab 6: Read-After-Write through Session Sticky Routing in Redis
**Status:** Accepted, amended by 0052 (`ForEventualReadAsync` → `EventualAsync`) · **Date:** 2026-11-08 · **Author:** Participant 1

## Context
With reads on the replica (ADR 0050) a user can miss their own write: the web UI opens a poll right after creating it, and
that `GET` would answer 404 from a replica that is behind. Explicit Primary Routing alone does not solve it: whether a poll
belongs to the reader is known only after reading it, and sending every authenticated read to the Primary would remove the
replica for logged-in users. Lab 6 (2.4) asks for one protective mechanism.

## Decision
- **Session Sticky Routing:** after a successful write, the user's eventual reads go to the Primary for
  `ReadAfterWrite:StickyTtlSeconds` (`STICKY_TTL_SECONDS`, default 5 s; 0 switches it off for the demo).
- **The mark lives in Redis** (`polling:sticky:{userId}`, value with a TTL), because the next request may reach another instance;
  an in-process mark would be hidden affinity (lab 2). The user comes from the JWT, so no cookies are needed.
- **Set in one middleware** (`UseStickyAfterWrite`) for every non-GET authenticated request with a 2xx answer, so a new write
  endpoint is covered automatically and a failed write sets nothing.
- **Set in `Response.OnStarting`**, before the client gets the answer: otherwise the client's next read could overtake the mark
  and reach the replica.
- **Checked lazily** in `ReadDb.ForEventualReadAsync(userId)`: only when a read really needs the database, and never for
  anonymous requests. A cache HIT and strict reads make no extra Redis call.
- **Redis down:** the check answers "sticky", so authenticated reads go to the Primary (safe direction: more load, not stale data);
  anonymous reads stay on the replica. The mark is best-effort, like cache invalidation (ADR 0043): a committed write stays a success.
- **Replaces the property `ReadDb.Eventual` from ADR 0050**, which could not take a user or call Redis.
- **Not built:** LSN verification. It is more exact (no TTL to guess) but needs an extra read of the WAL position after each
  write, a place to carry it, and a comparison before each read. It is the first thing to reach for if lag regularly exceeds the TTL.

## Consequences
- `scripts/stale-read-demo.py`, 2 full runs, ALL PASSED, with `recovery_min_apply_delay` = 3 s: an anonymous reader gets 404 from
  the replica (Stale Read) and sees the poll after 2.5–2.9 s; the author gets 200 from the Primary on both instances; after the TTL
  the author reads the replica again. With TTL 0 the author gets 404 for their own poll.
- **Known limit, shown by the demo:** lag longer than the TTL (8 s vs 5 s) gives the author 404 once the TTL ends. Idle lag is about
  10 ms, so 5 s leaves a wide margin at rest; the lag under write load is measured in stage 5.
- Protection covers one user's own writes. Other users are still eventually consistent, on purpose.
- Scenario C of lab 5 writes often, so more of its reads will go to the Primary. That is the price of the guarantee and belongs in the
  stage 5 report.
- With a 3 s lag `cross-instance.sh` passes 7 of 8: step 5 reads anonymously and correctly gets a stale 404. Without artificial lag it passes 8 of 8.

**Results MISS on the replica, measured (decision of ADR 0050).** The MISS was temporarily switched to the replica (reverted, not
committed), `cache-race-check.py`, 60 rounds each:

| Results MISS reads from | No artificial lag | Lag 200 ms | Lag 1 s |
|---|---|---|---|
| Replica (experiment) | 11, 6 stale rounds | 60 stale rounds | stale, e.g. 0 served of 64 votes (count not captured) |
| Primary (real code) | 0 | 0 | 0 |

Stale aggregates reach the shared cache even at the natural lag of a few milliseconds, so this confirms the decision.
