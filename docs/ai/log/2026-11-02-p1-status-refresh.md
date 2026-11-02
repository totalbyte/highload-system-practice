# 2026-11-02 — Participant 1 — Status refresh after PR #9 – #11; labs 2 and 3 defended
**Lab:** 2, 3 · **Commits:** branch `docs/labs-2-3-defended`, PR into `main`

## Goal
Participant 1 suspected `docs/ai/status.md` had been missed. Check it against the repository and bring it up to date.

## Done
- Confirmed `docs/ai/status.md` was part of PR #9 and Participant 1's edits survived the later merges of
  `lab3/p2-experiments` (PR #10, #11).
- Rewrote the stale shared parts: lab 3 intro (all task branches merged, defense material), the joint table (was still
  titled for lab 2; С-1 … С-5 now reflect PR #11: С-3 done, С-4 dry run done by Participant 2, joint rehearsal and С-5
  left), lab 2 С-6 (merged via PR #9, lecturer page `docs/about/lab2.md`), the lab 2 / lab 3 rows in «All labs»,
  repository state (PR #9 – #11 with merge hashes, the folder rename, no open PRs), next steps.
- `CLAUDE.md` knowledge map pointed to `docs/defense/lab2.md` / `lab3.md`, but `1c03d0d` renamed the folder to
  `docs/about/` — link fixed.
- Participant tables (П1, П2) left untouched.
- Participant 1 reported that the joint rehearsals happened and labs 2 and 3 are defended: status (current lab → 4,
  lab 2 / 3 ✅, С-4 / С-5 ✅, next steps = lab 4 task split), `labs/lab2-summary.md` marked defended,
  new `labs/lab3-summary.md` (from README «Підсумок лаби 3», ADRs 0031–0037 and the status tables), labs index.

## Decisions (link ADRs)
None.

## Problems & fixes
- Broken `CLAUDE.md` link after the `docs/defense` → `docs/about` rename (`git grep` found no other references outside
  the session logs).

## Verified (how)
- `gh pr view 9 --json files` lists `docs/ai/status.md`; `git show origin/main:docs/ai/status.md` reviewed line by line.
- Merge hashes checked with `git log origin/main`; `git grep "docs/defense"` → only the intentional rename note in
  status. Docs only — no code or stack change, smoke test not needed.

## Not done / next steps
- Review and merge the `docs/labs-2-3-defended` PR.
- Lab 4 task split. Questions asked at the lab 2 / 3 defenses are not recorded.
