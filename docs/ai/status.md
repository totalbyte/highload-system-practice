# Project status

> Snapshot of the current state. **Rewrite outdated lines in place** — history belongs in `log/`.
> Last updated: 2026-10-27 by Participant 1 (lab 2 task split, see `log/2026-10-27-p1-lab2-task-split.md`).

## Current lab: 2 — Stateless architecture

Task lists (Ukrainian, task ids П1-N / П2-N / С-N): [`docs/lab2/participant-1.md`](../lab2/participant-1.md),
[`docs/lab2/participant-2.md`](../lab2/participant-2.md). Their «Домовленості» section (branches, file ownership,
ADR number ranges 0021–0025 / 0026–0030, ports 8080 / 8082, Redis contract) is a **proposal not yet confirmed by
Participant 2** (task С-1).

To avoid merge conflicts, each participant edits **only their own table** below.

### Participant 1

| Task | Status |
|---|---|
| П1-1 Redis + `backend-1` / `backend-2` in compose (branch `lab2/p1-infra`) | ⏳ |
| П1-2 Concurrent cold start of two instances on an empty DB (ADR 0009 "Unverified") | ⏳ |
| П1-3 DataProtection keys → shared store | ⏳ |
| П1-4 State audit: platform modules | ⏳ |
| П1-5 Cross-instance consistency chain (`requests/cross-instance.http`, `scripts/cross-instance.sh`) | ⏳ |
| П1-6 C4 component diagram + multi-instance deployment docs | ⏳ |
| П1-7 Smoke test on both instances, docs | ⏳ |

### Participant 2

| Task | Status |
|---|---|
| П2-1 State audit: voting and results modules | ⏳ |
| П2-2 "Before" demo: stale results across instances with the in-memory cache (must precede П2-3) | ⏳ |
| П2-3 `ResultsCache` → Redis (supersedes ADR 0013) | ⏳ |
| П2-4 Redis unavailable → 503, committed vote not reported as failed | ⏳ |
| П2-5 Stateless request flow for `POST /vote` | ⏳ |
| П2-6 The three concurrency checks across two instances | ⏳ |
| П2-7 Instance-loss test (`docker compose kill` during voting) | ⏳ |
| П2-8 README sections, docs | ⏳ |

### Joint (after all lab 2 branches are merged)

С-1 agree on the proposals · С-2 PR reviews · С-3 consolidated README audit · С-4 code audit (grep for in-process
state) · С-5 cold-start defense rehearsal · С-6 `labs/lab2-summary.md` — all ⏳.

## All labs

| Lab | Status |
|---|---|
| 1 System Design + MVP | 🟡 stages 1–9 done; stage 10 (cold-start defense rehearsal) and `labs/lab1-summary.md` not recorded |
| 2 Stateless | 🟡 planned (task split 2026-10-27); groundwork from lab 1: JWT, `X-Instance-ID`, advisory-locked seed |
| 3 Horizontal Scaling | ⏳ (groundwork: `/health`) |
| 4 Distributed Caching | ⏳ |
| 5 Load Testing | ⏳ (groundwork: 500 seed users, hot poll #1) |

## Repository state

- Branch `main`, remote `origin` = https://github.com/totalbyte/highload-system-practice.
- `fix/lab1-review-findings` (review fixes, ADRs 0017–0019, pgAdmin ADR 0020) is merged into `main` via PR #1
  (`06692fe`, 2026-10-21).
- No branching convention agreed yet; the lab 2 files propose `lab2/p1-infra`, `lab2/p1-platform`, `lab2/p2-voting`.
- No automated tests — verification is the runbook smoke test, the three concurrency checks and the per-option
  counter query (last full run 2026-09-30: 48/48, also on a cold start).
- `.gitattributes` keeps LF in the repository. If Git shows whole-file changes after a pull, run
  `git add --renormalize .` and check that `git diff --cached` is empty — then nothing really changed.

## Next steps

- **Both:** С-1 — read both `docs/lab2/participant-*.md` files and confirm or adjust the proposals.
- **Participant 1:** П1-1 + П1-2 first and merge `lab2/p1-infra` early — it unblocks Participant 2.
- **Participant 2:** П2-1 and П2-5 while waiting (no infra dependency); П2-2 strictly before П2-3. Read ADR 0017
  (merged with PR #1: `VoteService` locks the vote row `FOR UPDATE`, option counters updated in ascending id order)
  before touching the vote path.
- **Lab 1 leftovers (if lab 1 is not defended yet):** cold-start defense rehearsal and `labs/lab1-summary.md`.
