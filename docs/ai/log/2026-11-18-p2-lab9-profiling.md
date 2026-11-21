# 2026-11-18 — Participant 2 — lab 9: profiling the catalog, auto-prepare
**Lab:** 9 · **Commits:** not committed

## Goal
Lab 9: take a measured degradation, prove its root cause with CPU / memory / DB / tracing instruments, fix it with one
targeted change and verify before / after.

## Done
- Branch `lab9/profiling` from `main` after PR #19 (lab 8) was merged; assignment `docs/labs/Lab9 - Performance Profiling.md`,
  plan `docs/lab9/plan.md`.
- Instruments: `pg_stat_statements` + `track_planning` on all four nodes; OpenTelemetry → Jaeger (`Common/Diagnostics/Tracing.cs`,
  profile `tracing`); dotnet-trace / counters / gcdump in the image; `profiling/collect.sh`, `flamegraph.py`, `summary.py`,
  `traces.py`, `pgbench/`.
- Evidence (`profiling/baseline`, `profiling/optimized`) and the cycle in `profiling/README.md`.
- Optimization: `Max Auto Prepare=20` (`DB_MAX_AUTO_PREPARE`).
- `profiling/ab-series.sh` + `ab-report.py`; `docs/lab9-guide.md`.
- Fix outside the lab's change: startup migrations under an advisory lock (`DatabaseInitializer`).
- A/B: ADR 0069, `profiling/ab-report.md`; README «Лабораторна 9», `docs/about/lab9.md`.
- Lab 7 docs: Mermaid charts with two bar series overlapped (the taller hid the other) → coloured lines / one bar series;
  `docs/about/lab7.md` rewritten with plain explanations in the text.

## Decisions (link ADRs)
- [0065](../decisions/0065-lab9-symptom-and-db-instrumentation.md), [0066](../decisions/0066-opentelemetry-jaeger.md),
  [0067](../decisions/0067-profiling-tools-and-evidence.md), [0068](../decisions/0068-auto-prepare-root-cause.md), [0069](../decisions/0069-lab9-ab-verification.md),
  [0070](../decisions/0070-migration-advisory-lock.md).

## Problems & fixes
- `pg_stat_statements` was not loaded on the replicas (lab 8 enabled it on the Primaries only) — added there.
- Several "load" runs were empty: k6's setup got 503 at login right after `up --wait` (HAProxy returns backends to the pool
  later) → wait for login 200; and `curl -o /dev/null` fails under `MSYS_NO_PATHCONV=1` with Windows curl → a temp file.
- Cold start: one backend sometimes crashed applying `ShardPollAggregate` twice on Shard A → advisory lock (ADR 0070).
- `dotnet-counters ps` does not list the app inside the container → `-p 1`; `dotnet-trace --profile cpu-sampling` is
  `collect-linux` only → `dotnet-sampled-thread-time`, flame graph from `CPU_TIME` samples.
- `summary.py`: CPU counter has two series (user / system) — summed; heap size read from the gcdump report header; UTF-8 stdout.

## Verified (how)
- Three cold starts after the migration fix: 0 restarts.
- `collect.sh baseline` / `optimized`, 50 VUs, 0 % errors: 411 → 588 RPS, p95 197 → 139 ms; planning on replica A
  14 734 → 71 ms per window; `prepared_ratio` 0 → 100 %.
- `pgbench` on replica A (one core): simple 822, extended 717, prepared 1723 tps (exploratory run: 1003 / 950 / 2514).
- Traces (300 sequential requests each): request 8.0 → 7.2 ms, SQL wall 5.1 → 4.3 ms (median).
- A/B (`ab-series.sh`, 0 % errors): catalog +41 … +58 % RPS, p95 −17 … −35 %; writes +31 … +81 %, reads +44 … +136 %.
- Smoke, `shard-routing-check`, `concurrency-checks` green on the default stack; 12 Mermaid diagrams of labs 7 / 9 rendered.

## Not done / next steps
- Commit; open a PR; defense rehearsal; `labs/lab9-summary.md` after the defense.
