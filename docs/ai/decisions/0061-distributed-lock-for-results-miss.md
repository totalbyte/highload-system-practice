# 0061. Lab 8: distributed lock in Redis behind single-flight — one DB load per invalidation for the cluster
**Status:** Accepted, single-run throughput corrected by 0064 · **Date:** 2026-11-17 · **Author:** Participant 1 · Amends 0044

## Context
Single-flight (ADR 0044) coalesces misses only inside one instance, so a stampede costs one DB load per instance:
2.0–2.2 on two backends (ADR 0060). Lab 8's defense asks to prove the reduction to **1**. ADR 0044 rejected a Redis
lock as "not worth it for 2–3 instances"; lab 8 asks exactly for it, and the grading criteria are "no deadlocks,
correct handling of TTL / timeouts in locks".

## Decision
- New mode `RESULTS_STAMPEDE_PROTECTION=Lock`, **now the default** (code and compose); `SingleFlight` and `None` stay
  for comparison.
- **Two levels.** Single-flight per instance stays in front, keyed by (poll, generation): only one request per
  instance talks to Redis. Inside the flight, `ResultsDistributedLock.LoadAsync`:
  1. `GET` the value of this generation — present → return it (a request that missed just before the store does not
     take the already free lock and does not read the DB again; that is what made "2.2 instead of 2" in ADR 0044);
  2. `SET polling:results:lock:{poll}:g{gen} <random token> NX PX 1000`;
     acquired → `GET` the value once more (the previous owner may have stored it and released the lock in between),
     otherwise read the Primary, store under that generation, release;
     busy → wait 10–20 ms (random, so waiters of different instances do not hit Redis in step) and repeat from 1;
     Redis unavailable → read the DB without the lock (the BYPASS idea of ADR 0043; `SetAsync` swallows failures).
- **Lock key contains the generation** — the same argument as ADR 0044: whoever waits for generation g read g before
  the invalidation to g + 1, and the value under g was read from the DB after its owner read g, i.e. after the commit.
  A read that starts after a mutation's response has g + 1 and never waits for an older load.
- **Release only one's own lock**: Lua `if GET == token then DEL`. After a lease expires another instance may already
  own the key; a plain `DEL` would remove its lock and let a third load run.
- **Timeouts — no deadlock by construction.**
  - Lease 1 s: a dead or hung owner frees the lock by itself. 1 s is ×20 the 50 ms simulated load and ×500 the real
    one. When a load outlives the lease, the next request takes the lock and loads again — a duplicate load, not an
    error: both write the same aggregate under the same generation (so no fencing token is needed: the "protected
    resource" is an idempotent cache write keyed by generation). The owner logs a Warning on a failed release.
  - Max wait 2 s (> lease): after it a waiter reads the DB itself — a last bound if Redis misbehaves.
  - The shared load ignores the client's cancellation (own scope, `CancellationToken.None`, as in ADR 0044); each
    request stops waiting on its own token.
- Single Redis node, so this is `SET NX` with a lease, not Redlock (5 independent masters, majority, clock-drift
  margin). Redlock and its critique (process pauses, fencing tokens) are theory for the defense.
- Waiters answer `X-Cache: MISS` (they missed) without `X-DB-Node` (their data came from Redis).

## Consequences
Measured 2026-11-17 with `load-tests/stampede.sh` (ADR 0060 stand, 500 VUs, 2 backends, 0 % errors):

| Run | SingleFlight | **Lock** |
|---|---|---|
| burst, real aggregate — DB loads per invalidation / p95 | 2.2 / 433 ms | **1.0** / 394 ms |
| burst, delay 50 ms — DB loads / p95 | 2.0 / 564 ms | **1.0** / 634 ms |
| sustained 30 s, delay 50 ms — DB loads / RPS / p95 / p99 | 2.2 / 2467 / 423 / 630 ms | **1.0** (128 for 130) / 3520 / 312 / 455 ms |

The sustained row is a single run each. **Corrected by ADR 0064** (median of 3): SingleFlight 2.2 / 3765 / 294 / 387 ms,
Lock 1.0 / 3420 / 257 / 397 ms — Lock is not faster than single-flight on two instances (−9 % RPS, −13 % p95); its gain is
the bound of one load however many instances there are.

Failure modes checked:
- **Dead owner** (`scripts/lock-check.py`): a planted lock with a foreign token and `PX 1000`, never released; 50 and
  200 simultaneous readers all got 200 at 1.01–1.02 s after it was planted, 1 DB load, no lock keys left.
- **Load longer than the lease** (`RESULTS_LOAD_DELAY_MS=1500`): 2.0 DB loads per invalidation, 0 errors, p95 2.6 s;
  both instances logged "lease expired before the load finished"; the token check kept the first owner from deleting
  the second owner's lock.
- Redis down: no lock, BYPASS as before (`redis-outage-check.py`).

Costs: waiters poll Redis every 10–20 ms (one request per instance per hot key); burst p95 is a little higher than
single-flight (waiters see the value up to one poll interval late); under a lease shorter than the load the
protection degrades to one load per lease period instead of failing.
