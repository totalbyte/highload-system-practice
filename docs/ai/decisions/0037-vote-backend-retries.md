# 0037. Lab 3: separate `be_vote` backend that retries an already-sent vote, with its own health checks
**Status:** Accepted (extends 0033) · **Date:** 2026-10-28 · **Author:** Participant 2

## Context
Lab 3 (2.4.3, defense item 3) asks that stopping a backend container mid-traffic redirects requests to healthy nodes
without 5xx for the client. ADR 0033 (Participant 1) gives `be_api` `/health` checks, `retries 2` +
`option redispatch 1`, passive `observe layer4`, and L7 retries (`retry-on conn-failure empty-response`) **only for
GET**: re-sending a POST/PATCH that already reached a node is unsafe in general (`POST /api/polls` would create a
second poll). 5xx are deliberately neither observed nor retried — the "503 trap": with Redis or the DB down every
instance honestly answers 503 at once, and treating that as a node failure would take the whole pool out.

`scripts/kill-test.py` (800 votes, 32 threads, `docker compose kill backend-1` after 10 %) through the balancer,
measured 2026-10-28:
- П1-1 config (TCP checks, no redispatch): 52 client errors (48 × 503, 4 × 502) up to 18 s after the kill, node DOWN
  after 11.2 s, 16 votes lost even after a client retry.
- П1-3 config (ADR 0033), votes through `be_api`: node DOWN after 0.9 s, **6 × 502** — the votes the killed node was
  processing; a client retry of each got 201 (they had not committed).

## Decision
- `frontend fe_api`: `use_backend be_vote if METH_POST { path_reg ^/api/polls/[0-9]+/vote$ }`; everything else stays
  in `be_api`.
- `be_vote` = `be_api` plus L7 retries for the vote: `retries 2`, `option redispatch 1`,
  `retry-on conn-failure empty-response` **without** `disable-l7-retry`, and `option http-buffer-request`: a request can
  only be replayed if HAProxy holds it whole; without it HAProxy forwarded the headers before the body arrived and the
  retry silently did not happen (502 `SH--` with 0 retries in the log, 0–6 per run on a cold stack). Safe for this one endpoint: the vote and the
  counter are one transaction (ADR 0014), so on a killed node it is either fully committed or rolled back by
  PostgreSQL; a retry after a commit gets 409 thanks to `UNIQUE(poll_id, user_id)`, a retried vote change to the same
  option gets 200 with no change — never a double vote.
- Not retried: 5xx (the 503 trap, same as ADR 0033) and `response-timeout` (30 s without an answer is a slow DB,
  not a dead node; a retry would double the load on it).
- **Own health checks, not `track be_api/backend-N`.** The same `/health` check line as `be_api` (`option httpchk`,
  `inter 2s fastinter 500ms fall 2 rise 2`, `timeout check 3s`) plus `observe layer4 error-limit 1 on-error mark-down`.
  Participant 1 suggested `track` (one set of probes). Measured with `track`: a tracking server has no passive check,
  and the votes no longer pass through `be_api`, so its `observe layer4` never sees their connection errors — the
  killed node stayed in the pool ≈ 6 s (two failed active checks), every vote sent to it waited the 2 s
  `timeout connect` before being redispatched (run 9.5 s instead of ≈ 6.5 s), and in 1 of 4 runs a vote got 502
  (client retry → 409: committed, response lost mid-flight). With own checks the first failed connection of a vote
  marks the node down in ≈ 1 s.
- Same `balance` and weights as `be_api`: `scripts/lb-algorithm.sh` (ADR 0034) rewrites every `balance` line and every
  `server backend-1 … weight N` line, so both sections always switch together (verified with `weighted` and back).

## Consequences
- Verified 2026-10-28, 2 instances, final config (with `http-buffer-request`), after a cold start: **6 kill runs +
  1 stop run, 5 600 votes, 0 client errors**; in one run 3 votes got **409** as their first answer — HAProxy
  retried votes that had committed on the killed node (`+1` retry in the log); the vote exists exactly once, which is
  the price stated above. Earlier runs without the buffering option: 0 errors in 9 of 10, but 6 × 502 on a cold stack; node DOWN in
  `be_vote` after 0.9–1.2 s (`be_api` 5.5–6 s — no traffic left there to observe); every vote 201, vote rows = users,
  per-option counters consistent, results through the balancer = DB; `docker compose start backend-1` → back UP in
  4–5 s, same results immediately. `concurrency-checks.py` through the balancer all green.
- `redis-outage-check.py` through the balancer: during the outage both nodes stay UP in both sections, the client gets
  our 503 ProblemDetails for results (not an HAProxy page), the vote is 201 and stored once — the 503 trap is avoided.
- Twice the `/health` probes (two sections × each node every 2 s) — a `SELECT 1`, negligible.
- Known limit: a response the node started sending and did not finish cannot be retried (HAProxy is already
  forwarding it). Not seen in 8 000 votes with this config; if it happens the client's own retry gets 409 and sees the
  vote exists.
- `kill-test.py` reports the DOWN time of both sections; `lb-distribution.py` / `lb-failover.py` (Participant 1) only
  use `be_api`, which is unchanged.
