# 0045. Lab 5: k6 in Docker inside the stack network, every component pinned to its own cores
**Status:** Accepted · **Date:** 2026-11-02 · **Author:** Participant 1, Participant 2

## Context
Lab 5 requires declarative load scripts in `/load-tests` (k6 / Locust / Gatling), a fixed and documented test
environment (2.2.2) and isolation between the load generator and the system under test (2.2.3). Lab 3 showed why the
last point matters here: on one 24-core machine without limits a single backend took 5.6 cores, a Python generator
capped at ≈ 1.8k rps, and 1 / 2 / 3 instances gave the same throughput. k6 is not installed on Participant 2's machine.

## Decision
- **k6 `grafana/k6:1.3.0`** as a compose service `k6` (profile `loadtest`, started only with `run --rm k6 run …`) in a
  separate overlay `load-tests/docker-compose.loadtest.yml`; the standard `docker compose up` is unchanged.
- k6 targets **`http://lb:8080` inside `app-network`**, not `localhost:8080`: no Windows → WSL2 port forwarding in the
  measured path (it adds latency and its own CPU use on the host).
- **Pinned cores and limits** (`cpuset` + `cpus` + `mem_limit`): lb `0-1`, backend-1 `2-3`, backend-2 `4-5`,
  backend-3 `6-7` (2 cores, 1 GB each), postgres `8-11` (4 cores, 2 GB), redis `12` (1 core, 256 MB), **k6 `16-23`**
  (8 cores the SUT never uses). Every instance is a "server" of fixed size, so adding one adds hardware.
- `load-tests/env-spec.sh` prints the environment of a run (host, per-container cpuset / limits, pool members,
  connection pool, cache switch, PostgreSQL and Redis settings) to be saved next to the results.

## Consequences
- Verified 2026-11-02: limits applied (`docker inspect`), `smoke.js` 5 VU × 10 s → 34 686 requests, ≈ 3 470 rps, p95
  2.3 ms, 0 errors; app smoke test 9/9.
- Docker Desktop's VM still shares host RAM and the host OS runs outside the cpusets — the isolation is good, not
  perfect; stated in the baseline card.
- Numbers from this overlay are not comparable with labs 3–4 (no limits there).
