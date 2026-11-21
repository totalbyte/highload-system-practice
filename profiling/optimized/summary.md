# Profiling summary: optimized

## Load (k6, catalog)

| VUs | RPS | p50 ms | p95 ms | p99 ms | errors % |
|---|---|---|---|---|---|
| 50 | 588 | 82.3 | 139.0 | 177.3 | 0.0 |

## Containers (average CPU over the window, max memory)

| container | CPU % | RAM MiB |
|---|---|---|
| backend-1 | 157 | 220 |
| backend-2 | 144 | 162 |
| lb | 33 | 84 |
| postgres | 3 | 65 |
| postgres-replica | 88 | 151 |
| postgres-shard-b | 3 | 52 |
| postgres-shard-b-replica | 101 | 151 |
| redis | 1 | 6 |

## backend-1 runtime (dotnet-counters, 30 s average)

| counter | value |
|---|---|
| CPU, cores (user + system) | 1.47 |
| GC pause, % of time | 1.32 |
| allocation rate, MB/s | 60.4 |
| GC collections / s, gen0 / gen1 / gen2 | 0.00 / 1.14 / 0.00 |
| thread pool queue length | 0.9 |
| thread pool threads | 4 |
| lock contentions / s | 0.4 |
| working set, MB | 255 |
| Npgsql prepared ratio, %, replica pools | 100, 100 |
| Npgsql connections used / idle, replica pools | 24.3, 3.4 / 5.7, 26.6 |
| Npgsql operation p95, replica pools, ms | 10.5, 73.1 |

## Heap (dotnet-gcdump, start vs end of the window)

Live objects: 11.2 MB → 11.8 MB (+5.0 %).

## Hot frames (CPU_TIME samples, inclusive)

| frame | % of CPU samples |
|---|---|
| `PollingPlatform.Api.Polls.PollService+<LoadListPartAsync>d__8.MoveNext` | 36.2 |
| `Microsoft.AspNetCore.Server.Kestrel.Core.Internal.Http.HttpProtocol+<ProcessRequests>d__23` | 30.7 |
| `PollingPlatform.Api.Polls.PollService+<ListAsync>d__6.MoveNext` | 26.5 |
| `PollingPlatform.Api.Polls.PollService+<LoadShardPartAsync>d__7.MoveNext` | 26.4 |
| `PollingPlatform.Api.Polls.PollsController+<List>d__3.MoveNext` | 26.3 |
| `PollingPlatform.Api.Data.ReadDb+<EventualAsync>d__7`1[System.ValueTuple`2[System.Int32,Sys` | 26.0 |
| `PollingPlatform.Api.Data.ReadDb+<ReadAsync>d__9`1[System.ValueTuple`2[System.Int32,System.` | 25.8 |
| `System.Threading.Thread.<PollGC>g__PollGCWorker|67_0` | 24.3 |
| `Microsoft.EntityFrameworkCore.Query.Internal.SingleQueryingEnumerable`1+AsyncEnumerator+<M` | 23.0 |
| `Npgsql.EntityFrameworkCore.PostgreSQL.Storage.Internal.NpgsqlExecutionStrategy+<ExecuteAsy` | 23.0 |
| `Microsoft.EntityFrameworkCore.Query.Internal.SingleQueryingEnumerable`1+AsyncEnumerator+<I` | 23.0 |
| `Microsoft.EntityFrameworkCore.Storage.RelationalCommand+<ExecuteReaderAsync>d__22.MoveNext` | 22.6 |

## pg-stat-statements-postgres-replica

```
 calls  | plan_ms | exec_ms | plan_per_call_ms | exec_per_call_ms | plan_pct |                                                          query                                                           
--------+---------+---------+------------------+------------------+----------+--------------------------------------------------------------------------------------------------------------------------
  55673 |      71 |   23600 |            0.001 |            0.424 |      0.3 | SELECT p.id, p.title, p.status, p.is_public, p.creator_id, p.creator_username, ( SELECT count(*)::int FROM options AS o 
  55671 |     115 |    5089 |            0.002 |            0.091 |      2.2 | SELECT count(*)::int FROM polls AS p WHERE p.is_public AND p.status <> 'draft' AND p.status = $1
 111324 |    2701 |    1143 |            0.024 |            0.010 |     70.3 | SELECT pg_advisory_unlock_all()
 111324 |       0 |    1354 |            0.000 |            0.012 |      0.0 | SET SESSION AUTHORIZATION DEFAULT
 111324 |       0 |     964 |            0.000 |            0.009 |      0.0 | RESET ALL
     10 |     156 |      24 |           15.611 |            2.373 |     86.8 | SELECT extract($1 FROM now())::int, coalesce(state, $2), coalesce(wait_event_type, $3), coalesce(wait_event, $4), count(
(6 rows)
```

## pg-stat-statements-postgres-shard-b-replica

```
 calls  | plan_ms | exec_ms | plan_per_call_ms | exec_per_call_ms | plan_pct |                                                          query                                                           
--------+---------+---------+------------------+------------------+----------+--------------------------------------------------------------------------------------------------------------------------
  52902 |       2 |   48807 |            0.000 |            0.923 |      0.0 | SELECT p.id, p.title, p.status, p.is_public, p.creator_id, p.creator_username, ( SELECT count(*)::int FROM options AS o 
  52883 |       1 |    4790 |            0.000 |            0.091 |      0.0 | SELECT count(*)::int FROM polls AS p WHERE p.is_public AND p.status <> 'draft' AND p.status = $1
 105784 |    2079 |     888 |            0.020 |            0.008 |     70.1 | SELECT pg_advisory_unlock_all()
 105784 |       0 |    1079 |            0.000 |            0.010 |      0.0 | SET SESSION AUTHORIZATION DEFAULT
 105784 |       0 |     819 |            0.000 |            0.008 |      0.0 | RESET ALL
 105784 |       0 |     131 |            0.000 |            0.001 |      0.0 | DISCARD SEQUENCES
(6 rows)
```
