# 0033. Active `/health` checks, passive layer-4 checks, retries to another node (lab 3)
**Status:** Accepted · **Date:** 2026-10-28 · **Author:** Participant 1

## Context
Lab 3 (2.4) requires a readiness endpoint, automatic exclusion of unavailable or degraded nodes by active and/or
passive checks, and no 5xx for the client when a backend container stops. ADR 0031 left plain TCP checks with
HAProxy defaults and recorded the gap: right after a node vanished, a request could hang ~8 s (4 × 2 s connect
timeouts, all to the same dead node) and get HAProxy's 503.

`/health` already exists (ADR 0012, 0019): its own `SELECT 1` to PostgreSQL with a 2 s timeout, 200 or 503, and it
deliberately ignores Redis (ADR 0021). Participant 2's artificial delay (ADR 0036) skips `/health`, so a slow node
stays in the pool.

## Decision
In `backend be_api` of `haproxy/haproxy.cfg`:
- **Active checks:** `option httpchk` + `http-check send meth GET uri /health` + `http-check expect status 200`;
  `inter 2s fastinter 500ms fall 2 rise 2`; `timeout check 3s` (> the 2 s `/health` needs to report a dead DB).
  A node whose `/health` answers 503 (no DB) is the "degraded" node of 2.4.2 and leaves the pool. The check request is
  HTTP/1.0 without `Host` — Kestrel accepts it (`L7OK 200`, ~1 ms).
- **Passive checks:** `observe layer4 error-limit 1 on-error mark-down` — the first connection failure on live
  traffic takes the node out at once, without waiting for `fall` failed checks. **Not `observe layer7`**: our API
  honestly answers 503 when Redis or the DB is unavailable (ADR 0016, 0027) — on every instance at once — and layer-7
  observation would then take the whole pool out. This is the "503 trap" to settle with Participant 2 (П2-4).
- **Retries:** `retries 2` + `option redispatch 1` — every retry goes to another node. Safe for any method: a failed
  connect means the request was never sent.
- **Retry after the request was sent:** `retry-on conn-failure empty-response` with
  `http-request disable-l7-retry if !METH_GET` — a GET whose node died mid-request (killed) is retried, POST / PATCH /
  DELETE are not (a repeated `POST /api/polls` creates a second poll). 5xx codes are not retried for the same reason as
  layer 7 above. Retrying `POST .../vote` is Participant 2's decision in a separate backend (П2-4); servers there can
  reuse these checks with `track be_api/backend-N`.

## Consequences
- Verified 2026-10-28 with `scripts/lb-failover.py` (8 threads of `GET /api/polls?pageSize=5` through :8080, node
  `backend-2` failed at 3 s, started at 10 s), two runs each:

  | Run | Requests | Client non-2xx / connection errors | Node out of the pool after | Retried on backend-1 | Back in the pool after `start` |
  |---|---|---|---|---|---|
  | `stop` #1 | 18 943 | 0 | 0.49 s | — | 7.8 s |
  | `stop` #2 | 20 924 | 0 | 0.44 s | 2 | 6.3 s |
  | `kill` #1 | 14 834 | 0 | 0.52 s (passive: "L4 unsuccessful connection") | — | 6.6 s |
  | `kill` #2 | 21 421 | 0 | 0.34 s | 7 | 6.8 s |

  The return time is mostly ASP.NET startup (migration and seed checks): from the first passed check (`DOWN 1/2`) to
  `UP` takes ~0.5 s (`fastinter`). Requests caught by the failure took up to ~1 s instead of ~20 ms; none failed.
- **PostgreSQL down** (all `/health` = 503): both nodes leave the pool ~4.6 s after `docker compose stop postgres`;
  until then a request may wait the API's 13–19 s and get our 503 ProblemDetails, afterwards every request gets
  HAProxy's own `503 text/html` "No server is available" within ~3 ms. After `start postgres` both nodes are back in
  ~2.3 s. Accepted: 2.4.1 asks for a DB-aware readiness check. Clients that parse `application/problem+json` should
  also accept a plain 503 from the balancer; an `errorfile 503` with a ProblemDetails body is possible if that
  becomes a problem.
- **Redis down** does not change any node's state (`/health` ignores Redis, no layer-7 observation): the API's own
  503 ProblemDetails reaches the client (to be confirmed by Participant 2 in П2-4).
- After every config reload the servers show `UP 1/3`-style states until the new worker's first check (≤ 2 s);
  cosmetic, they keep serving.
- Supersedes the "known gap" note of ADR 0031.
