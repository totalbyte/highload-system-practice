# 2026-11-11 — Participant 1 — lab 6: lecturer page reworked
**Lab:** 6 · **Commits:** not committed (Participant 1 commits personally)
## Goal
Participant 1 found `docs/about/lab6.md` too thin on test results, with the Stale Read section hard to follow. Rework it item by item against the assignment.
## Done
- `docs/about/lab6.md` rewritten: every section is requirement → what was done → measured result → where in the repo.
- Added: the topology / R-W diagram (§3 asks for it); `replication-check` results as a table; the classification as business operations with reasons;
  measured replication lag without artificial delay; the stale read demo as a timeline (who reads, answer, node, what it shows); exact failure numbers per operation;
  for 2.6 per-step tables (RPS · p95 · p99, averages of runs) for A with cache on and off, A + writes, B, C, a saturation-point table, a resource table explaining
  why RPS does not grow, two charts; short definitions in the theory section; demo durations and expected endings.
- Section 4 then rewritten on request into a per-endpoint list in plain language: writes, strict reads, eventual reads, the results special case,
  and when the route changes (sticky, replica down, primary down). Endpoints checked against the controllers and the code paths using `ReadDb`.
## Decisions (link ADRs)
None new. Saturation points read from the averaged tables: A 25 VU, A + writes 50 VU, B 10 VU, C 100 VU in both configurations.
## Problems & fixes
- Some failure ranges were first written too narrow (vote 12–87 ms, login 24–75 ms); checked against all runs and widened (12–104, 24–99).
## Verified (how)
- Averages computed from the k6 JSON and resource files with `report.py`; every number cross-checked against the run outputs. Links checked, all 3 Mermaid diagrams rendered in a browser with a local mermaid 11.4.0.
## Not done / next steps
- C differs by one run per configuration; the page says it is not a conclusion. Rehearsal, PR, defense, `labs/lab6-summary.md` as before.
