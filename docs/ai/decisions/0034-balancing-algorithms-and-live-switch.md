# 0034. Balancing algorithms: round robin by default, live switch with one script (lab 3)
**Status:** Accepted · **Date:** 2026-10-28 · **Author:** Participant 1

## Context
Lab 3 (2.3, §4 items 1–2) asks for round robin with distribution statistics, at least one alternative (least
connections, weighted round robin, IP hash), and a live algorithm change at the defense with an explanation of the
difference. ADR 0031 established the reload mechanism (`docker compose kill -s USR2 lb`).

## Decision
- **Default `balance roundrobin`.** After lab 2 every instance is stateless and identical, and most requests are short
  and similar — the profile round robin fits. Least connections is the choice once request durations differ or a node
  degrades (Participant 2's experiment, П2-3).
- **All four algorithms are one command away:** `bash scripts/lb-algorithm.sh roundrobin|leastconn|weighted|source`.
  The script rewrites the `balance` line and the weight of `backend-1` in `haproxy/haproxy.cfg`, validates the file
  with `haproxy -c` inside the `lb` container (a broken file is restored and never reloaded), then reloads with
  SIGUSR2. `weighted` = round robin with `weight 3` on `backend-1` (a node "three times stronger"); `source` = hash of
  the client IP, HAProxy's equivalent of IP hash. Every server line carries an explicit `weight` so the script only
  edits numbers. Without an argument it prints the current algorithm.
- Not chosen: four backends (one per algorithm) with `use_backend` switched by one line — it would quadruple the health
  checks and split the stats page across four pools; an environment variable in the config — HAProxy reads the
  environment only at process start, so switching would need a container restart instead of a reload.
- **Statistics:** `python scripts/lb-distribution.py [-n 300] [--path ...]` sends N sequential GETs over one keep-alive
  connection (HAProxy balances each HTTP request, not the connection) and prints the split by `X-Instance-ID` next to
  the per-server response counters from the stats page (`/stats;csv`, `hrsp_*` delta) — both always matched exactly.
- Git Bash on Windows rewrites `/usr/local/...` arguments to Windows paths; the script sets `MSYS_NO_PATHCONV=1` for
  `docker compose exec` (harmless elsewhere).

## Consequences
- Measured 2026-10-28, 300 × `GET /health`, sequential (one request in flight at a time):

  | Algorithm | 2 instances (b1 / b2) | 3 instances (b1 / b2 / b3) |
  |---|---|---|
  | `roundrobin` | 50.0 / 50.0 % | 33.3 / 33.3 / 33.3 % |
  | `leastconn` | 52.7 / 47.3 % | 31.0 / 34.0 / 35.0 % |
  | weighted 3 : 1 (: 1) | 75.3 / 24.7 % | 60.3 / 19.7 / 20.0 % |
  | `source` | 0 / 100 % | 0 / 100 / 0 % |

  Least connections ≈ round robin here because with one request in flight every node has 0 active connections —
  ties are broken in turn; its difference shows only under concurrency with unequal durations (П2-3). `source` sends
  everything to one node because all host traffic reaches the Docker network from one gateway address (`172.20.0.1`
  in the HAProxy log) — the NAT effect that makes IP hash harmful for a stateless API.
- Live switch under load: `scripts/load.py --scenario mixed --threads 16 --duration 14` with RR → LC → RR switched in
  the middle: 8365 requests at 596 rps, 0 5xx, 0 connection errors (one 409 from two first votes of the same user,
  unrelated to the balancer).
- The script edits a tracked file; after a demo run `bash scripts/lb-algorithm.sh roundrobin` (or `git checkout
  haproxy/haproxy.cfg`) so the default stays round robin in Git.
