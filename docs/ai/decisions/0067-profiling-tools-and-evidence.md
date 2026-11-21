# 0067. Lab 9: dotnet-trace / dotnet-counters / dotnet-gcdump in the backend image, one evidence script under the same load
**Status:** Accepted · **Date:** 2026-11-18 · **Author:** Participant 2

## Context
Lab 9 (2.2, §3) asks for CPU and memory profiling (hot paths, allocation rate, GC pauses, heap snapshots), database
diagnostics and artifacts in `/profiling` (flame graphs, heap snapshots, EXPLAIN ANALYZE). The runtime image has no SDK,
and the containers are not privileged (no `perf`).

## Decision
- **Tools in the image:** `dotnet-trace`, `dotnet-counters`, `dotnet-gcdump` 10.0.750501 installed with `dotnet tool
  install --tool-path /tools` in the build stage and copied into the runtime image (`PATH` includes `/tools`); run with
  `docker compose exec backend-1 <tool> ... -p 1` (inside the container the app is PID 1, `ps` of `dotnet-counters` does not
  list it, `-p 1` works).
- **CPU profile = sampled thread time** (`--profile dotnet-common,dotnet-sampled-thread-time`, ~100 Hz). Kernel CPU sampling
  (`collect-linux`) needs admin rights. Thread time includes waiting threads, so `profiling/flamegraph.py` keeps only the
  stacks that end in the pseudo-frame `CPU_TIME` (managed code on a CPU) for the flame graph and drops the service frames
  of process and thread, so stacks of all threads merge; `--all` keeps everything (wall clock).
- **`profiling/collect.sh <label>`:** fresh stack on `docker-compose.loadtest-shards.yml` (one core per database node, as
  in lab 7), waits until login answers 200 (HAProxy returns backends to the pool later than compose reports them healthy —
  without this k6's setup got 503 and the "load" was empty), k6 catalog 50 VUs × 100 s; during the steady part: two heap
  snapshots, `dotnet-counters` 30 s (`System.Runtime`, `Npgsql`, ASP.NET Core), `dotnet-trace` 15 s, `docker stats` and
  `pg_stat_activity` samples; afterwards `pg_stat_statements` of both replicas, EXPLAIN (ANALYZE, BUFFERS) of both catalog
  queries (third run of three in one session), `topN` reports, flame graphs, `summary.py` → `summary.md`.
- **Artifacts in Git:** flame graphs (SVG), topN, counters CSV, heap snapshots (`.gcdump`) and their
  reports, EXPLAIN outputs, `pg_stat_statements`, summaries. Raw `.nettrace` / `.speedscope.json` (20–30 MB) and the folded stacks (6–8 MB) are in
  `.gitignore`; `collect.sh` recreates them.
- **Isolating H3 outside the application:** `pgbench` on a replica with the same two catalog statements, protocols
  `simple`, `extended` (what Npgsql does without preparation) and `prepared`, 20 clients × 15 s (`profiling/pgbench/`).

## Consequences
- Baseline evidence (2026-11-18, 50 VUs, 411 RPS, 0 % errors): replica B 101 % / replica A 90 % CPU, backends 115–132 % of
  200 %; backend: GC pause 0.94 % of time, 42 MB/s allocated, heap of live objects 10.2 → 10.7 MB over the window (no leak),
  thread-pool queue 0.2, CPU_TIME only 10.9 % of sampled thread time (threads mostly wait for the database); Npgsql
  `prepared_ratio` 0 on both replica pools; `pg_stat_statements`: planning 48 % (A) / 19 % (B) of the page query's time and
  56–61 % of the count query's, plus one `DISCARD ALL` per pool return; EXPLAIN: index scan, the correlated `count(options)`
  is 20 × 0.017 ms. `pgbench` (`profiling/pgbench/results.txt`, replica limited to exactly one core): 822 tps simple, 717 extended,
  **1723 prepared** (×2.4); an exploratory run the same day gave 1003 / 950 / 2514 (×2.6).
- Verdict: H1 refuted (index used, idle execution 0.5 ms), H2 present but cheap, H4 a consequence (the slow replica keeps
  ≈ 24 of 30 connections busy), H5 refuted (GC < 1 %, no heap growth, threads wait); **H3 is the root cause** (ADR 0068).
- `dotnet-gcdump` warns that lossless buffering needs .NET 11; the heap here is ~10 MB, so the snapshots are complete enough.
- The `PollGC` frame takes ≈ 25 % of the CPU_TIME samples while the GC pause counter says < 1 %: the thread-time sampler
  attributes threads parked at a GC safe point to CPU_TIME. The counters are the measurement, the frame is noted, not used.
