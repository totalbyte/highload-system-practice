# 2026-10-27 — Participant 1 — Lab 2 task split
**Lab:** 2 · **Commits:** not committed

## Goal
Read the lab 2 assignment and the repository, split lab 2 between the two participants so both can work in parallel
in their own branches, and estimate the AI-assisted chat time.

## Done
- Compared the lab 2 `.docx` with `docs/labs/Lab2 - Stateless Architecture.md` — identical text.
- Scanned the code for in-process state: `ResultsCache` (`IMemoryCache` singleton) and file-based DataProtection keys
  are the critical items; JWT, the advisory-locked seed, `vote_count` and the vote locks are already shared (DB);
  the remaining singletons/statics hold no data. ADR 0009 (concurrent `MigrateAsync`) is still unverified.
- Wrote `docs/lab2/participant-1.md` and `docs/lab2/participant-2.md` (Ukrainian): tasks П1-1…П1-7, П2-1…П2-8,
  joint С-1…С-6, each with the lab clause it covers, done criteria and time; plus identical shared sections
  (parallel-work rules, lab 2 scope limits, order of work, lab-requirement coverage matrix, defense theory).
  Checked that the shared sections are byte-identical in both files.
- Rewrote `status.md` for lab 2 (one table per participant to avoid merge conflicts); noted that PR #1 is merged.

## Decisions (link ADRs)
No ADRs — the proposals below are not yet confirmed by Participant 2 (task С-1):
- Redis arrives in lab 2, but the results cache moves there "as is" (same key, 10 s TTL, same invalidation);
  key schema, `X-Cache`, fallback, stampede protection and cold/hot latency stay in lab 4.
- No load balancer in lab 2: `backend-1` on 8080, `backend-2` on 8082 (8081 is Adminer), `INSTANCE_ID=backend-1/2`.
- Branches `lab2/p1-infra` (merged first), `lab2/p1-platform`, `lab2/p2-voting`; ADR ranges 0021–0025 / 0026–0030.
- Participant 1 registers one `IConnectionMultiplexer`; Participant 2 adds no NuGet packages (no `.csproj` conflict).
- The cross-instance chain (lab 2.5, first bullet) is owned by Participant 1 and covers polls, votes and results;
  the instance-loss test (second bullet) by Participant 2.

## Problems & fixes
- The lab 2 `.docx` was read with Python `zipfile` (no `python-docx` / `pandoc` on this machine).

## Verified (how)
- Shared sections of the two task files compared with `awk` + `cmp` — identical; every lab 2 requirement (2.1–2.6,
  §3, §4) maps to at least one task in the coverage matrix.
- No code changed, so the smoke test was not run.

## Not done / next steps
- Participant 2 to review the task split and confirm the proposals (С-1).
- Then П1-1 + П1-2 (Participant 1) and П2-1 + П2-5 (Participant 2) in parallel.
