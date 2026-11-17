# 2026-11-17 — Participant 1 — review of PR #17 (lab 7) and its fixes
**Lab:** 7 · **Commits:** not committed (merge of `main` into `lab7/sharding` is staged, not committed)
## Goal
Review PR #17 against the lab 7 assignment, run it from a cold start, fix what the review found.
## Done
- Review: every item 2.1–2.6 and §3 is covered. Cold start 78 s with the build, no manual steps. `shard-routing-check`,
  `cross-shard-check`, `concurrency-checks`, `replication-check --shard A / B`, `db-failure-check` passed. The k6 series
  (`series-lab7.sh`) was not re-run: the numbers are taken from the documents.
- `ShardRouter`: a negative `poll_id` under `Range` (≤ −RangeSize) or `Modulo` (odd negative) gave a negative shard index →
  `IndexOutOfRangeException` → 500. Now the shard index is clamped / normalised, so such an id is a 404. `scripts/shardlib.py`
  mirrors it (`max(0, …)` for Range; Python `%` is already non-negative).
- Catalog: a shard is skipped (`X-Shard-Unavailable`) only when the monitor sees no live node (`ShardContexts.IsDown`). A timeout on
  a live shard used to silently drop it from a 200 response; now it is a 503 (`TimeoutException` → 503 "database").
- `PollListQuery.Page` is limited to 1..10000: `page=21474837&pageSize=100` overflowed `Page * PageSize` and gave 500; now 422.
- Wording «запис і читання одного опитування ×1.9» (README, `docs/about/lab7.md`, `docs/lab7-guide.md`) corrected: the test spreads
  votes over 40 polls, one viral poll stays on one shard (as ADR 0054 says).
- Merge of `origin/main` (PR #18, lab 6 lecturer page) into the branch: the only conflict was `docs/ai/status.md` (header line).
## Decisions (link ADRs)
- ADR 0057 amended (catalog skips only a shard the monitor sees as dead); `contracts.md`: `page` 1..10000.
## Problems & fixes
- The first check of negative ids after switching strategy hit a stack that was still starting (HAProxy 503): wait for
  `GET /api/polls/1` = 200 before probing.
## Verified (how)
- Rebuilt from the working tree, default `Buckets`: `page=21474837` → 422, `page=10000` → 200; `shard-routing-check`,
  `cross-shard-check` (Shard B stopped: catalog 200 with `X-Shard-Unavailable: B`, B poll 503), `db-failure-check` ALL PASSED.
- `Modulo` and `Range` stacks: `GET /api/polls/-1, -2, -7, -5000` → 404, no `IndexOutOfRange` in backend logs;
  `shard-routing-check` ALL PASSED for both.
## Not done / next steps
- Participant 2 commits the changes on `lab7/sharding` (merge commit of `main` + the fixes); the PR description wording
  «одного опитування» on GitHub is still the old one.
- Left as design risks, not defects: Shard A is a single point of failure for login and poll creation; resharding is a model only.
