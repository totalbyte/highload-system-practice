# Profiling summary: baseline

## Load (k6, catalog)

| VUs | RPS | p50 ms | p95 ms | p99 ms | errors % |
|---|---|---|---|---|---|
| 50 | 411 | 117.5 | 196.6 | 245.3 | 0.0 |

## Containers (average CPU over the window, max memory)

| container | CPU % | RAM MiB |
|---|---|---|
| backend-1 | 132 | 213 |
| backend-2 | 115 | 194 |
| lb | 25 | 84 |
| postgres | 4 | 57 |
| postgres-replica | 90 | 136 |
| postgres-shard-b | 4 | 50 |
| postgres-shard-b-replica | 101 | 146 |
| redis | 1 | 6 |

## backend-1 runtime (dotnet-counters, 30 s average)

| counter | value |
|---|---|
| CPU, cores (user + system) | 1.19 |
| GC pause, % of time | 0.94 |
| allocation rate, MB/s | 42.0 |
| GC collections / s, gen0 / gen1 / gen2 | 0.00 / 0.83 / 0.00 |
| thread pool queue length | 0.2 |
| thread pool threads | 4 |
| lock contentions / s | 0.5 |
| working set, MB | 248 |
| Npgsql prepared ratio, %, replica pools | 0, 0 |
| Npgsql connections used / idle, replica pools | 24.1, 1.6 / 5.9, 26.4 |
| Npgsql operation p95, replica pools, ms | 107.2, 13.1 |

## Heap (dotnet-gcdump, start vs end of the window)

Live objects: 10.2 MB → 10.7 MB (+4.5 %).

## Hot frames (CPU_TIME samples, inclusive)

| frame | % of CPU samples |
|---|---|
| `PollingPlatform.Api.Polls.PollService+<LoadListPartAsync>d__8.MoveNext` | 34.8 |
| `Microsoft.AspNetCore.Server.Kestrel.Core.Internal.Http.HttpProtocol+<ProcessRequests>d__23` | 30.0 |
| `PollingPlatform.Api.Data.StickySessionsExtensions+<>c__DisplayClass0_0.<UseStickyAfterWrit` | 27.2 |
| `PollingPlatform.Api.Polls.PollService+<ListAsync>d__6.MoveNext` | 26.1 |
| `PollingPlatform.Api.Polls.PollService+<LoadShardPartAsync>d__7.MoveNext` | 26.1 |
| `PollingPlatform.Api.Polls.PollsController+<List>d__3.MoveNext` | 26.0 |
| `PollingPlatform.Api.Data.ReadDb+<EventualAsync>d__7`1[System.ValueTuple`2[System.Int32,Sys` | 25.7 |
| `PollingPlatform.Api.Data.ReadDb+<ReadAsync>d__9`1[System.ValueTuple`2[System.Int32,System.` | 25.5 |
| `System.Threading.Thread.<PollGC>g__PollGCWorker|67_0` | 25.5 |
| `Microsoft.EntityFrameworkCore.Query.Internal.SingleQueryingEnumerable`1+AsyncEnumerator+<M` | 22.1 |
| `Npgsql.EntityFrameworkCore.PostgreSQL.Storage.Internal.NpgsqlExecutionStrategy+<ExecuteAsy` | 22.0 |
| `Microsoft.EntityFrameworkCore.Query.Internal.SingleQueryingEnumerable`1+AsyncEnumerator+<I` | 21.9 |

## pg-stat-statements-postgres-replica

```
 calls | plan_ms | exec_ms | plan_per_call_ms | exec_per_call_ms | plan_pct |                                                          query                                                           
-------+---------+---------+------------------+------------------+----------+--------------------------------------------------------------------------------------------------------------------------
 38958 |   14734 |   15866 |            0.378 |            0.407 |     48.2 | SELECT p.id, p.title, p.status, p.is_public, p.creator_id, p.creator_username, ( SELECT count(*)::int FROM options AS o 
 38948 |    5687 |    3687 |            0.146 |            0.095 |     60.7 | SELECT count(*)::int FROM polls AS p WHERE p.is_public AND p.status <> $2 AND p.status = $1
 77904 |       0 |    1991 |            0.000 |            0.026 |      0.0 | DISCARD ALL
    10 |     224 |     218 |           22.359 |           21.778 |     50.7 | SELECT extract($1 FROM now())::int, coalesce(state, $2), coalesce(wait_event_type, $3), coalesce(wait_event, $4), count(
   224 |      18 |       9 |            0.082 |            0.039 |     68.1 | SELECT $1
     1 |       0 |       0 |            0.309 |            0.064 |     82.8 | SELECT pg_stat_reset()
(6 rows)
```

## pg-stat-statements-postgres-shard-b-replica

```
 calls | plan_ms | exec_ms | plan_per_call_ms | exec_per_call_ms | plan_pct |                                                          query                                                           
-------+---------+---------+------------------+------------------+----------+--------------------------------------------------------------------------------------------------------------------------
 36826 |   16124 |   66968 |            0.438 |            1.818 |     19.4 | SELECT p.id, p.title, p.status, p.is_public, p.creator_id, p.creator_username, ( SELECT count(*)::int FROM options AS o 
 36801 |    4837 |    3792 |            0.131 |            0.103 |     56.1 | SELECT count(*)::int FROM polls AS p WHERE p.is_public AND p.status <> $2 AND p.status = $1
 73626 |       0 |    1575 |            0.000 |            0.021 |      0.0 | DISCARD ALL
   217 |      11 |       4 |            0.049 |            0.020 |     70.7 | SELECT $1
     0 |       0 |       0 |            0.413 |            0.000 |    100.0 | SELECT calls, round(total_plan_time::numeric) AS plan_ms, round(total_exec_time::numeric) AS exec_ms, round((total_plan_
     1 |       0 |       0 |            0.000 |            0.166 |      0.0 | SELECT pg_stat_statements_reset()
(6 rows)
```
