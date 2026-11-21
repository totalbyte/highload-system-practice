# 0066. Lab 9: distributed tracing with OpenTelemetry → Jaeger, off by default, HTTP-rooted sampling
**Status:** Accepted · **Date:** 2026-11-18 · **Author:** Participant 2

## Context
Lab 9 (2.2) asks to decompose the total latency of a request into service, cache and database parts with distributed
tracing (OpenTelemetry / Jaeger / Zipkin). The catalog request fans out to both shards in parallel (ADR 0055), so one
request has several database calls whose times overlap.

## Decision
- **Instrumentation in the backend** (`Common/Diagnostics/Tracing.cs`): OpenTelemetry with ASP.NET Core (server span),
  Npgsql (`Npgsql.OpenTelemetry`, one span per SQL statement with the text and the node) and StackExchange.Redis (beta
  package, one span per command); OTLP gRPC export.
- **Jaeger `jaegertracing/jaeger:2.12.0`** (v2, in-memory storage), UI on `localhost:16686`, compose profile `tracing`:
  a normal `docker compose up` does not start it.
- **Off by default** (`TRACING_ENABLED=false`): creating and exporting spans costs CPU and would bias the A/B measurements.
  `TRACING_SAMPLE_RATIO` (default 1.0) for runs under load.
- **Sampler:** a trace starts only from an HTTP server span; root spans of other kinds are dropped — otherwise the node
  monitor's `SELECT 1` every second (ADR 0052) would be a separate trace each time. `/health` is filtered out too.
- **`profiling/traces.py`** sends sequential catalog requests, reads the traces through the Jaeger API and reports the
  median / p95 of the whole request, the SQL wall time (union of the overlapping per-shard intervals) and the rest of the
  backend; it saves one full trace as `trace-example.json`.

## Consequences
- Measured 2026-11-18, sequential requests on an idle stack, 300 traces each: before the optimization the request took
  8.0 ms (median), SQL wall 5.1 ms, backend outside SQL 2.9 ms, one SQL statement ≈ 1.7 ms on either replica, 4 statements
  per request; after it 7.2 / 4.3 / 2.9 ms, one statement ≈ 1.3 ms. On an idle stack the database part shrinks a little;
  the large effect shows only under load, where the replicas are the bottleneck (ADR 0069).
- Packages: `OpenTelemetry.Extensions.Hosting`, `.Instrumentation.AspNetCore`, `.Exporter.OpenTelemetryProtocol` 1.21.0,
  `Npgsql.OpenTelemetry` 10.0.3, `OpenTelemetry.Instrumentation.StackExchangeRedis` 1.21.0-beta.1 (only a beta exists).
