# 0031. HAProxy as the single entry point; backends without host ports; `backend-3` in the `scale` profile (lab 3)
**Status:** Accepted · **Date:** 2026-10-28 · **Author:** Participant 1

## Context
Lab 3 requires a load balancer in front of a pool of at least two backend replicas, with the clients talking only to
the balancer (2.2: no access to the instances' private addresses), active and passive health checks (2.4.2),
several balancing algorithms switched live at the defense (2.3, §4), and scale-out runs on 1 / 2 / 3+ instances
(2.5). Lab 1 named Nginx in the stack and ADR 0021 said "lab 3 will put Nginx in front".

## Decision
- **HAProxy, not Nginx.** Open-source Nginx has no active health checks (only NGINX Plus does), while the lab grades
  "automatic recovery and degradation of the pool" — a node must leave and rejoin the pool by its `/health`, not when a
  client request has already failed on it. HAProxy (free) has active checks (`option httpchk`, `inter` / `fall` /
  `rise`), passive ones (`observe`), retries to another node (`retries` + `option redispatch`, `retry-on`),
  `roundrobin` / `leastconn` / `weight` / `source`, and a built-in statistics page that shows per-node requests, state
  and response times at the defense. Full comparison: `docs/lab3/participant-1.md`, «Домовленості».
- **Image `haproxy:3.4.6-alpine`**: the 3.4 LTS line, an exact tag one patch behind the newest (3.4.7 on 2026-10-28),
  same reasoning as ADR 0020. Config `haproxy/haproxy.cfg`; the whole `haproxy/` directory is bind-mounted read-only
  (a single-file bind mount keeps the old inode when an editor on Windows replaces the file, so edits would not be
  seen).
- **Ports.** `lb` publishes `${LB_PORT:-8080}` (the old `backend-1` port, so the runbook smoke test,
  `requests/polls.http` and habits keep working) and `${LB_STATS_PORT:-8404}` (`/stats` — the balancer's own UI, not a
  backend). `backend-1..3` publish nothing: reachable only inside `app-network` as `backend-N:8080`. `API_PORT` /
  `API2_PORT` are gone from `.env.example`.
- **`backend-3`** is the same YAML anchor with `profiles: ["scale"]`, so the normal `docker compose up` keeps two
  instances and `docker compose --profile scale up -d` adds the third. `lb` `depends_on` only `backend-1` / `backend-2`
  (a dependency on a service of an inactive profile is an error).
- **Runtime DNS.** `resolvers docker` (Docker DNS `127.0.0.11`) and `default-server init-addr none resolvers docker`:
  server addresses come only from the runtime resolver. A server without a DNS record (`backend-3` not running) sits
  in `MAINT (resolution)` instead of failing the start, and is picked up when the container appears; a restarted
  container's new IP is picked up too. Not `init-addr last,libc,none` as first planned: a libc lookup of a
  non-existent name through Docker DNS (forwarded to the host's resolver) takes ~6 s, and that delay hit **every
  config reload** (measured: reload 6.5 s with `libc`, 0.37 s with `none`) — bad for the live algorithm switch.
- **Timeouts.** `timeout connect 2s`: inside the bridge network a connection takes well under 1 ms, so 2 s means a dead
  node. `timeout client` / `timeout server 30s`: the longest legitimate API answer is 13–16 s while PostgreSQL is down
  (EF retries, then our 503 ProblemDetails, runbook) — the client must get that 503, not a 504 from the balancer.
  `timeout http-request 10s` against slow clients.
- **Logs.** `option httplog` on the frontend, to stdout (`docker compose logs lb`): client, backend/server (`%s`),
  timers `Tq/Tw/Tc/Tr/Ta`, status (`%ST`), termination state. The stats page is not logged (`no log`, it refreshes every
  2 s).
- **Health checks in this step** are plain TCP `check` with HAProxy defaults (inter 2 s, rise 2, fall 3). `/health`
  checks, passive checks and `option redispatch` are task П1-3 (separate ADR).
- **Live reload** without rebuilding or restarting the container: the image runs HAProxy in master-worker mode (`-W`),
  so `docker compose kill -s USR2 lb` makes the master re-read the mounted config and start a new worker; the old one
  finishes its connections. Verified: a `balance roundrobin` → `leastconn` switch under a stream of 60 requests — 0
  non-200, container `StartedAt` unchanged.

## Consequences
- Verified 2026-10-28 on a cold start (`docker compose down -v && docker compose up -d --build`): no manual steps;
  `X-Instance-ID` alternates `backend-1` / `backend-2`; `curl localhost:8082` → connection refused; `docker compose ps`
  shows backends with `8080/tcp` only; `--profile scale up -d` → `backend-3` UP on the stats page after ~9 s without
  restarting `lb`, then 30 requests split 10 / 10 / 10; seed ran once (500 users, 50 polls); smoke test 11/11 through
  :8080.
- During a cold start HAProxy answers its own `503` ("no server available") for the few seconds until the backends
  finish migrations and the seed and start listening; the log shows `backend 'be_api' has no server available!` once.
  Expected.
- **Known gap until П1-3:** right after a backend disappears, HAProxy still considers it UP for up to `inter × fall`
  (≈ 6 s with the TCP defaults). Observed: after `docker compose rm -sf backend-3` one request went to the removed
  node, the connect timed out 4 times (2 s × default `retries 3` + 1, all to the same node, no `redispatch`) and the
  client got a 503 after 8 s (`sC--`). П1-3 adds `/health` checks, `option redispatch` and tuned `inter` / `fall`.
- The lab 2 tools that address `backend-2` directly on :8082 (`scripts/cross-instance.sh`, Participant 2's Python
  scripts, `requests/cross-instance.http`) no longer reach it; they move to the balancer in П1-5 / П2-7. Direct access
  to an instance, if needed, goes into a separate `docker-compose.debug.yml` (8091–8093), never the standard stack.
- Connection budget with three instances: 3 × 30 = 90 ≤ 97 (ADR 0018); 4+ instances — task П1-2.
- HAProxy logs `Automatically setting global.maxconn to 524263` (derived from the container's file-descriptor limit).
  Harmless for the lab; per-server `maxconn` is not set, so `leastconn` sees the backends' real concurrency.
- One HAProxy is a single point of failure — by design for the lab stand; Keepalived / VRRP and DNS round robin are
  covered in the README (П1-6), not deployed.
- Amends ADR 0021 (per-instance host ports 8080 / 8082 are gone).
