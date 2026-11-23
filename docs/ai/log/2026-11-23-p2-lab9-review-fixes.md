# 2026-11-23 — Participant 2 — lab 9: PR #20 review fixes
**Lab:** 9 · **Commits:** see the PR #20 commit after `5cd462f`

## Goal
Answer the review of PR #20: unexplained Shard B numbers, weak A/B statistics, raw results not in the repository, the
optimization not singled out, tracing taken only on an idle stack, the flame graph's limited value, an unlock in `finally`
that could hide the migration's exception.

## Done
- Shard B explained: full page (20 active public polls vs 12 on A) → 1.2–1.4× more work per request → B saturates first and
  its statements queue for the CPU (1.82 vs 0.41 ms per page call under load, 0.110 vs 0.087 ms idle). Formulations fixed:
  planning is 48 % of the page's time on A, 19 % on B (planning itself 0.38–0.44 ms on both).
- `profiling/pgbench/run.sh`: both replicas, 3 interleaved runs per mode, waits for WAL replay; results A ×2.45, B ×2.1.
- `ab-report.py`: min–max per configuration, worst … best delta, CPU only from samples inside a step with their count;
  reads the raw runs from the new `profiling/ab-results/`; `ab-series.sh` copies them there.
- `traces.py`: Redis time, `--kind catalog|results`, `--label idle|load`; traces before / after on idle and under 50 VUs.
- `profiling/stats-check.md`: 2 × 2 planner statistics × prepare.
- `DatabaseInitializer`: unlock only after a successful migration.
- Docs: `profiling/README.md` (Shard B, tracing, flame graph vs `pg_stat_statements`, exact diff of the optimization, A/B with
  bounds, day-to-day level), README «Лабораторна 9», `docs/about/lab9.md`, `docs/lab9-guide.md` (review questions as Q&A),
  ADR 0066, 0067, 0069, 0070.

## Decisions (link ADRs)
- No history rewrite to separate the optimization commit: the branch already has a merge of `main` by Participant 1; the
  optimization is four lines of `docker-compose.yml` (10–23), pointed to in every document instead.

## Problems & fixes
- `pgbench` today gave 3749 / 9194 tps vs 717 / 1723 on 2026-11-18 with the same limits; the catalog "before" 1300–1400 RPS
  vs ≈ 400. Checked the planner-statistics hypothesis with a 2 × 2 experiment — only 6–9 %; the machine itself was slower that
  day. Only same-day interleaved configurations are compared; the ratios (prepare ×2.1–2.5 in pgbench, +41 … +53 % in k6)
  are stable across days.
- `docker stats` takes ≈ 13 s per sample with all containers (not 5 s) — explains the odd CPU at 50 VUs.
- Large heredocs fail in the Bash tool → edits through small Python scripts.

## Verified (how)
- `pgbench/run.sh`: spread 1–5 % within a mode.
- 2 × 2 statistics check, traces before / after, cold start with the new unlock (0 restarts), `shard-routing-check` ALL PASSED.

## Not done / next steps
- Merge PR #20 after review; defense rehearsal; `labs/lab9-summary.md` after the defense.
