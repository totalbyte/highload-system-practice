# 0044. Lab 4: single-flight per instance against Cache Stampede
**Status:** Accepted · **Date:** 2026-11-02 · **Author:** Participant 1

## Context
In our high-load scenario every vote to the hot poll bumps its generation (ADR 0041), so right after each vote every
dashboard reader misses at once and each of them recomputes the same aggregate in PostgreSQL — a Cache Stampede /
Thundering Herd driven by invalidation, not by TTL expiry. Its size ≈ reads per second × recompute time. Idle, the
recompute takes ~2 ms and the herd is small; under peak voting the vote transactions hold almost the whole pool
(lab 3 П2-6: 26–29 of ≈ 30 sessions in `Lock`), the recompute waits for a connection, the herd grows and takes even
more connections — a feedback loop exactly when the cache matters most.

Measured before this change with `scripts/cache-stampede-check.py` (100 simultaneous reads of poll #1 right after an
invalidation, 20 rounds, 2 instances, idle stack): **6.7 / 10.7 / 14.4 DB loads per invalidation on average**, up to
98 of 100 in the first round of a run (cold connections → slow recompute → bigger herd).

Options considered (theory for the defense):
- **Single-flight in process** — concurrent misses of one instance share one DB load. Chosen.
- **Distributed lock in Redis** (`SET … NX PX`) — one load for the whole cluster instead of one per instance, at the
  price of extra Redis round-trips, waiting / polling and lock-owner failure handling. Not worth it for 2–3 instances.
- **Stale-while-revalidate** — serve the previous generation while one request refreshes. Rejected: breaks 2.5 (the
  voter would not see their own vote).
- **Probabilistic early expiration (XFetch)** — targets TTL-driven stampedes; ours are invalidation-driven.
- **Debounced invalidation** (at most once per N ms) — rejected for the same reason as stale-while-revalidate.

## Decision
- `Results/ResultsSingleFlight.cs`, singleton: `ConcurrentDictionary<(pollId, generation), Lazy<Task<CachedPollResults>>>`.
  On a miss `ResultsService` calls `LoadAsync(pollId, generation, ct)`: the first caller starts the load, the rest of the
  instance's concurrent misses for the same key await the same task. The load reads PostgreSQL, writes the entry under
  that generation (`SetAsync`) **before** leaving the table, then removes itself.
- **Key = (pollId, generation)** keeps ADR 0041's guarantee. Everyone in the flight for generation g read g, i.e.
  read it before the invalidation that moved the counter to g + 1 — so every one of them started before that
  mutation's response, and pre-mutation data is a legitimate answer for them. A read that starts after a mutation's
  response reads ≥ g + 1 and can only join a flight for that newer generation, whose DB read started after its
  starter read g + 1, i.e. after the commit. `cache-race-check.py` stays at 0 of 60.
- The shared load runs in **its own DI scope** and with `CancellationToken.None`: the request that started it may be
  aborted (client gone) and its scope disposed while others still wait. Each waiter stops waiting on its own token
  (`WaitAsync(ct)`). The DB query is still bounded by the command timeout and EF retries.
- Errors are shared: a missing poll gives every waiter its 404; a DB failure gives every waiter the same 503 (ADR 0016)
  and the next request starts a new load.
- **Not used for BYPASS** (Redis down, ADR 0043): without a generation one cannot tell whether an in-flight load
  started after a mutation's response, so joining it could return pre-mutation data. In degraded mode every read still
  goes to the DB on its own.
- Waiters still answer `X-Cache: MISS` — the data did not come from Redis; joining is logged at Debug
  ("MISS joined an in-flight load"). The state is only requests in progress: nothing is lost if the instance dies, so
  it does not contradict the stateless audit of lab 2.

## Consequences
- Verified 2026-11-02, same script after the change: **2.1 / 2.1 / 2.4 / 2.2 DB loads per invalidation** (max 3) with
  100 readers and 2.2 (max 3) with 200 — one per instance, sometimes one extra: a reader whose Redis lookup missed just
  before the load stored the entry and that reached the table just after the load left it. Regression: smoke 25/25,
  `cache-race-check.py` 3 × 0 of 60, `concurrency-checks.py`, `cross-instance.sh` 8/8, `redis-outage-check.py`,
  `cache-demo.py` (rc 0); `cache-latency.py` unchanged (MISS p50 3.78, HIT 1.97 ms).
- The bound is "instances", not 1: with N instances a stampede costs N loads. A distributed lock would be the next step
  if the pool grows large; for 2–3 instances it is noise.
- What single-flight does **not** fix: the hit ratio under peak voting. At ~250 votes/s an entry lives ~4 ms before
  the next invalidation, so most reads still miss — they are just cheap now (one load per instance per vote instead of
  one per reader). Measuring that under real load is lab 5.
- Not exercised by a test: a client aborting while others wait on its load (covered by design: own scope, no shared
  token).
