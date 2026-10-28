# 2026-10-28 — Participant 2 — lab 3: experiments through HAProxy (П2-3 … П2-7)
**Lab:** 3 · **Commits:** not committed (branch `lab3/p2-experiments`, rebuilt on `main` + `lab3/p1-platform`)

## Goal
Finish Participant 2's part of lab 3 once Participant 1's balancer was available: RR vs Least Connections with a slow
node, node loss during voting, scale-out 1/2/3, the next bottleneck, lab 2 scripts through the balancer.

## Done
- П2-3: 200 ms on `backend-2` (ADR 0036), `load.py read` 32 threads × 20 s × 3: RR 50/50, ≈ 300 rps, p95 209 ms,
  `backend-1` idle at ≈ 35 % CPU; leastconn 97.5/2.5, 1708–2007 rps, p95 23–28 ms; p99 ≈ 215 ms in both (2.5 % of the
  requests still go to the slow node). Control without delay: leastconn 50/50 like RR. README section + "which
  algorithm for which profile" table.
- П2-4: `scripts/kill-test.py` rewritten for the balancer (no client-side failover; client errors counted; one client
  retry to check exactly-once; DOWN time per HAProxy section from the stats CSV). `be_vote` backend in
  `haproxy/haproxy.cfg` with in-flight retries for `POST …/vote` and its own checks. ADR 0037.
- П2-5 / П2-6: scale-out series; README «Scale-out» and «Наступний bottleneck».
- П2-7: `concurrency-checks.py` / `redis-outage-check.py` default to the balancer; `results-cache-demo.py` docstring →
  `docker-compose.debug.yml`; runbook (kill test, Redis outage, parallel generators, scale-out with `cpus: 1`, DB wait
  query), contracts (`be_vote`), status.

## Decisions (link ADRs)
- [0037](../decisions/0037-vote-backend-retries.md): `be_vote` retries an already-sent vote (one transaction +
  `UNIQUE` make it safe); 5xx and `response-timeout` not retried; **own checks instead of `track be_api/...`** —
  Participant 1's suggestion, measured: with `track` the node stayed in the pool ≈ 6 s and one vote got 502 in 4 runs.

## Problems & fixes
- The first scale-out series was flat for reads **and** writes. Reads: one Python generator caps at ≈ 1.8k rps (GIL);
  three in parallel ≈ 4.8k — still flat, because containers have no CPU limits and one backend alone did ≈ 5k rps on
  5.6 of 24 cores. Fixed the method: `cpus: 1.0` per backend in the local override → read 1491 / 2785 / 3218 rps.
- My sampling query had `GROUP BY 1` on an expression containing `count(*)` → error; the first series has no
  `pg_stat_activity` wait data (fixed; the capped write series has it: `Lock` = 26–29 of ≈ 30).
- PRs #6 and #7 were merged while I worked and the remote branch got a merge from `main`; rebuilt the local branch on
  `origin/main`, fast-forwarded `lab3/p1-platform`, re-applied the work from a stash (no conflicts).
- One kill-test run failed only its last check (4 reads after the restart could all land on `backend-2`); now it reads
  until `backend-1` answers (≤ 10).
- `haproxy -c` from Git Bash: MSYS rewrites `/usr/local/...` → use `MSYS_NO_PATHCONV=1`.

## Verified (how)
See README tables. Kill test with the final config (`http-buffer-request`, cold start): 6 kill + 1 stop runs, 0 client errors, 3 votes 409 after an HAProxy retry of a committed vote, DOWN in
`be_vote` 0.9–1.2 s; `redis-outage-check.py` and `concurrency-checks.py` through the balancer all green; smoke 9/9;
`lb-algorithm.sh weighted` / `roundrobin` switches both sections. Final cold-start re-run before committing — see the
end of the session.

## Not done / next steps
Merge order: PR #8 (`lab3/p1-platform`) first, then this branch. С-3 README consolidation (Participant 2 leads), С-4
defense rehearsal, С-5 `labs/lab3-summary.md`. The 15–20 % rps spread of `write` runs (same poll, growing contention
as all 300 users have voted) is noted, not investigated further.
