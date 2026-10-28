# 2026-10-28 — Participant 1 — Lab 3 П1-3 … П1-7: health checks, algorithms, lab 2 chain via the balancer, docs
**Lab:** 3 · **Commits:** three commits on `lab3/p1-platform` (from `main` `65f5ded`), PR into `main`

## Goal
After PR #7 (П1-1, П1-2) and Participant 2's PR #6 (П2-1 delay, П2-2 `load.py`) were merged, do the rest of
Participant 1's lab 3 part: algorithms and their live switch (П1-4), health checks and node exclusion (П1-3), the lab 2
chain through the balancer (П1-5), diagram / deployment / SPOF docs (П1-6) and the close-out (П1-7).

## Done
- **П1-4:** every `server` line got an explicit `weight`; `scripts/lb-algorithm.sh roundrobin|leastconn|weighted|source`
  rewrites `balance` and the weight of `backend-1`, validates with `haproxy -c` inside `lb` (restores the file on
  failure), reloads with SIGUSR2. `scripts/lb-distribution.py`: N sequential GETs over one keep-alive connection, split by
  `X-Instance-ID` next to the per-server response deltas from `/stats;csv`. ADR 0034.
- **П1-3:** `option httpchk` + `http-check send meth GET uri /health` + `expect status 200`, `timeout check 3s`;
  `default-server ... inter 2s fastinter 500ms fall 2 rise 2 observe layer4 error-limit 1 on-error mark-down`;
  `retries 2`, `option redispatch 1`, `retry-on conn-failure empty-response` + `http-request disable-l7-retry if
  !METH_GET`. `scripts/lb-failover.py [--kill]`: GET stream, stop/kill `backend-2` at 3 s, start at 10 s, watches the
  stats page for the node's state. ADR 0033.
- **П1-5:** `scripts/cross-instance.sh` rewritten — both addresses default to :8080, every step is checked (code and key
  field), summary "steps passed: N / 8; served by ...", exit code; `requests/cross-instance.http` on :8080;
  `docker-compose.debug.yml` (ports `127.0.0.1:8091/8092/8093`, never in the standard stack).
- **П1-6:** README lab 3 subsections «Алгоритми», «Health checks», «Відмова вузла: читання», «Архітектура і
  розгортання» (Mermaid: client → host ports → `lb` → pool → PostgreSQL / Redis, private `app-network`), «SPOF» (table
  Keepalived/VRRP vs DNS RR vs cloud LB + VIP diagram); lab 2 architecture bullet points to lab 3; repo structure; RACI
  rows for lab 3; the lab 3 intro note about :8082. Runbook: «Load balancer (lab 3)», debug overlay, quirk rows (retried
  request ~1 s, `haproxy.cfg` modified after a demo, HAProxy 503 while the DB is down). Contracts: LB behaviour other code
  relies on, debug overlay.
- **П1-7:** status (my table, lab table, repository state, next steps), ADR index (0033, 0034), this log.

## Decisions (link ADRs)
- [ADR 0033](../decisions/0033-health-checks-and-retries.md): active `/health` checks + passive layer-4 mark-down,
  retries to another node; L7 retries only for GET; no layer-7 observation and no 5xx retries (the "503 trap").
  To be confirmed with Participant 2 in П2-4.
- [ADR 0034](../decisions/0034-balancing-algorithms-and-live-switch.md): `roundrobin` by default; one script edits
  the config and reloads; rejected: four backends with `use_backend`, environment variables (need a restart).
- `docker-compose.debug.yml` was made (the task left it optional) because Participant 2's historical
  `results-cache-demo.py` needs direct instance access (П2-7); recorded in the runbook and contracts, no ADR.

## Problems & fixes
- `lb-algorithm.sh` first reported "config check failed" every time: Git Bash (MSYS) rewrote the container path
  `/usr/local/etc/haproxy/haproxy.cfg` to `C:/Program Files/Git/usr/local/...`. Fixed with `MSYS_NO_PATHCONV=1` for
  that `docker compose exec`. The safety net worked: the file was restored, `lb` never got a bad config.
- After every reload the stats page shows `UP 1/3` until the new worker's first check (≤ 2 s, observed 0.2 → 2.1 s) —
  cosmetic, documented.
- Checked that a CRLF `haproxy.cfg` (what a Windows clone with `autocrlf=true` produces) passes `haproxy -c` — no
  `.gitattributes` change needed.
- A Python bulk edit of `cross-instance.sh` failed on an escaping mismatch (nothing written); the old script ran once
  against :8082 and failed as expected. Rewrote the file with the editor instead.

## Verified (how)
- Distribution (300 × `GET /health`): 2 instances RR 50/50, LC 52.7/47.3, weighted 75.3/24.7, source 0/100; 3 instances
  RR 33.3 each, LC 31/34/35, weighted 60.3/19.7/20, source 0/100/0; script and HAProxy counters equal every time
  (`stot` = responses except attempts retried elsewhere).
- Live switch RR → LC → RR in the middle of `load.py --scenario mixed --threads 16 --duration 14`: 8365 requests,
  596 rps, 0 5xx, 0 connection errors (one 409 = two first votes of one user, from `load.py`).
- `lb-failover.py`: stop 18 943 / 20 924 requests, kill 14 834 / 21 421 — 0 non-2xx / connection errors in all four; node
  out after 0.34–0.52 s (kill: "Health analyze ... L4 unsuccessful connection"), 2 and 7 requests redispatched
  (`+1` in the log), back 6.3–7.8 s after `start` (first passed check → UP ≈ 0.5 s).
- PostgreSQL stopped: both nodes DOWN after 4.6 s, then HAProxy `503 text/html` in ~3 ms; back 2.3 s after start. The
  first request before detection waited 18.8 s and got the API's 503 ProblemDetails.
- `cross-instance.sh` via the balancer 8/8 (4 steps per instance); with the debug overlay and `I1/I2` on 8091/8092
  8/8; back to the standard stack → `:8092` refused.
- Final cold start (`--profile scale down -v && up -d --build`): both nodes UP by `/health` after 18 s; runbook smoke
  test 11/11 through :8080 (counters 0, seed 500 users); `cross-instance.sh` 8/8; distribution 150/150;
  `lb-failover.py --kill` 0 errors of 17 558. `haproxy.cfg` left on `roundrobin`.

## Not done / next steps
- Review of the `lab3/p1-platform` PR by Participant 2 (С-2), then merge.
- Agree ADR 0033's choices with Participant 2 before / during П2-4 (no layer-7 observation, no 5xx retries; vote
  backend may `track be_api/backend-N`).
- П1-2 second criterion: `pg_stat_activity` ≤ 90 during Participant 2's three-instance runs (П2-5).
- Joint: С-1 (formal confirmation), С-2 reviews, С-3 (README comparison table — my distribution table is in place),
  С-4 rehearsal, С-5 `labs/lab3-summary.md`; lab 2 С-5 / С-6 still open.
