# Lab 3 summary — Horizontal scaling and load balancing

**Status:** ✅ defended (rehearsed together first). Merged into `main`: PR #6, #10, #11 (Participant 2), PR #7, #8
(Participant 1). Defense guide (Ukrainian): [`docs/lab3-guide.md`](../../lab3-guide.md); lecturer page:
[`docs/about/lab3.md`](../../about/lab3.md); README «Лабораторна 3» incl. «Підсумок лаби 3».

## What was built
- **HAProxy 3.4 LTS** (`haproxy:3.4.6-alpine`) as the single entry point on :8080, stats on :8404; backends publish no
  ports; `backend-3` in profile `scale`; runtime Docker DNS (`init-addr none`); reload with `docker compose kill -s USR2 lb`
  (ADR 0031). Direct instance access only via `docker-compose.debug.yml` (127.0.0.1:8091–8093).
- **Connection budget:** pool 30 for 1–3 instances (≤ 90 of 100); 4+ → `DB_MAX_POOL_SIZE = floor(90 / N)` (ADR 0032).
- **Health checks** on `be_api`: active `GET /health` (`inter 2s fastinter 500ms fall 2 rise 2`), passive `observe layer4`
  mark-down, `retries 2` + `redispatch 1`, L7 retries only for GET; no layer-7 observation / 5xx retries ("503 trap")
  (ADR 0033). **`be_vote`** (Participant 2) — own checks and safe retries for `POST .../vote` (ADR 0037).
- **Algorithms:** `roundrobin` default; `scripts/lb-algorithm.sh` switches roundrobin / leastconn / weighted / source live
  (ADR 0034). Slow-node experiment via `Diagnostics:ArtificialDelayMs` middleware (ADR 0036) and `scripts/load.py`.

## Key numbers
| Experiment | Result |
|---|---|
| Distribution, 2 / 3 instances (П1-4) | RR 50/50 · 33/33/33; LC 53/47; weighted 75/25 · 60/20/20; source 0/100 (one Docker gateway IP) |
| Slow node +200 ms (П2-3) | RR: 50 % on it, ≈ 300 rps, p95 209 ms; LC: 2.5 %, 1.7–2.0k rps, p95 23–28 ms; p99 ≈ 215 ms in both |
| Node failure, reads (П1-3) | 4 runs, ≈ 76k requests, 0 client errors, node out in 0.3–0.5 s |
| Node failure, votes (П2-4) | 7 runs, 5 600 votes, 0 client errors (3 × 409 after a committed retry), node out ≈ 1 s |
| Scale-out with `cpus: 1` per backend (П2-5) | read 1491 / 2785 / 3218 rps; write 108 / 153 / 242 → plateau ≈ 250–300; DB connections 77–79 of 90 |
| Next bottleneck (П2-6) | row locks on hot `options.vote_count` rows (`Lock` = 26–29 of ≈ 30 active); then the connection budget for 4+ |
| PostgreSQL down | whole pool out in ~4.6 s → HAProxy 503 `text/html` in ~3 ms; back ~2.3 s after start |

## Defense notes
- Why HAProxy, not Nginx: active health checks are free in HAProxy (NGINX Plus only), built-in stats page.
- Least Connections is the better choice for our mixed profile; neither algorithm fixes p99 with a slow node.
- SPOF of the balancer: Keepalived / VRRP (VIP, active-passive), DNS round robin, cloud LB — theory and diagram only.
- What the lecturer asked was not recorded.

## Carried into lab 4
Results cache work deferred since lab 2: key schema, TTL rationale, `X-Cache`, DB fallback when Redis is down,
cache-stampede protection, the invalidation race (ADR 0026 / 0027).
