# 2026-10-28 — Participant 2 — lab 3: artificial delay (П2-1) and load generator (П2-2)
**Lab:** 3 · **Commits:** not committed (branch `lab3/p2-experiments`)

## Goal
Do the two Participant 2 tasks of lab 3 that do not depend on the load balancer (task split: PR #5).

## Done
- П2-1: `Common/Diagnostics/ArtificialDelay.cs` — `app.UseArtificialDelay()` in `Program.cs` right after
  `UseInstanceIdHeader`; `Diagnostics:ArtificialDelayMs` > 0 delays every request except `/health`, 0 (default) does
  not register the middleware; startup warning when enabled.
- П2-2: `scripts/load.py` — closed-loop generator (threads with keep-alive connections, fixed duration, `--runs`),
  scenarios read / write / mixed on a fresh `allowVoteChange` poll; prints rps, p50/p95/p99/max, codes, split by
  `X-Instance-ID` with per-instance latency, run summary with the rps spread, per-option counter check after writes.
- `.gitignore`: `docker-compose.override.yml` (the delay lives there, locally).
- Docs: ADR 0036 + index row, runbook (load generator, slow-instance override), contracts, code guide, status.

## Decisions (link ADRs)
- [0036](../decisions/0036-artificial-delay-middleware.md): middleware rather than `tc netem` or a slow endpoint;
  `/health` not delayed so active checks keep the slow node in the pool; `Task.Delay` models I/O-bound slowness.

## Problems & fixes
- Right after `docker compose up -d backend-2` the first requests take 0.2–0.7 s even without the delay (JIT
  warm-up) — looked like the delay was still on; checked `printenv` in the container. Noted in the runbook: measure
  from the second request.

## Verified (how)
Cold start (`down -v` → `up -d --build`), no override: smoke test 9/9 on both instances, results after a postgres
restart 200, counters 0, no delay warning in the logs; `concurrency-checks.py` all passed; `dotnet build` 0 warnings.
`load.py` with the client-side split over 8080/8082, 32 threads × 10 s × 3 runs: read 1884 / 1968 / 1964 rps,
p99 ≈ 43 ms; write 318 / 271 / 254 rps, p99 ≈ 1 s, counters 0. With 200 ms on `backend-2`: requests there ~215 ms
vs ~20 ms on `backend-1`, `/health` fast on both, startup warning present. Override removed afterwards.

## Not done / next steps
П2-3 … П2-7 wait for `lab3/p1-lb` (HAProxy). The write scenario's 20 % rps spread between runs is worth a look before
П2-5 (growing vote count on the same poll? warm-up?) — run longer or with a fresh stack per run.
