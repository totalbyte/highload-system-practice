# 0036. Lab 3: artificial delay on one instance via middleware (`Diagnostics:ArtificialDelayMs`)
**Status:** Accepted · **Date:** 2026-10-28 · **Author:** Participant 2

## Context
Lab 3 (2.3.3) asks for a synthetic latency delay on one backend instance to compare Round Robin and Least
Connections by resource use and system p99. The delay has to be switchable per instance without rebuilding the
image, and it must not change the normal stack. Options considered:
- **Network delay with `tc netem`** inside the container: the `aspnet` image has no `iproute2`, and the container
  would need `NET_ADMIN` — more moving parts, and it also slows `/health` and the DB/Redis traffic of that instance.
- **A delay endpoint** (`/api/slow`): only that endpoint is slow, so it does not model a degraded node — the balancer
  would see a fast node with one slow URL.
- **Middleware that delays every request on that instance** — chosen.

## Decision
- `Common/Diagnostics/ArtificialDelay.cs`: `app.UseArtificialDelay()` (right after `UseInstanceIdHeader`, so the
  delayed responses still carry `X-Instance-ID`). Reads `Diagnostics:ArtificialDelayMs` once at startup; **0 or
  missing (the default) → the middleware is not added at all**. When enabled it logs a warning at startup.
- The delay is `await Task.Delay(delay, context.RequestAborted)` before the rest of the pipeline.
- `/health` is **not** delayed: the node is slow but alive. With active checks in the balancer (HAProxy, lab 3) a
  delayed `/health` could time out and drop the node from the pool — that would turn the "slow node" experiment
  into a "dead node" one.
- Enabled only through a local, gitignored `docker-compose.override.yml` with `Diagnostics__ArtificialDelayMs: 200`
  on one instance (example in the runbook). Not in `docker-compose.yml` or `appsettings.json`.

## Consequences
- Verified 2026-10-28 on two instances (no balancer yet): with 200 ms on `backend-2` its requests take ~215 ms vs
  ~20 ms on `backend-1`, `/health` stays ~10–20 ms on both, the startup warning appears in the `backend-2` logs; without
  the variable latency is unchanged (smoke test 9/9 on both instances).
- `Task.Delay` holds neither CPU nor a thread: it models a slow dependency / I/O-bound node, **not** an overloaded
  CPU. A slow node therefore keeps many requests in flight cheaply — exactly what Least Connections reacts to.
  Say this at the defense; a CPU-bound slow node would also need fewer threads or a CPU limit (`cpus:` in compose).
- A client that disconnects cancels the wait (`RequestAborted`), so abandoned requests don't pile up.
