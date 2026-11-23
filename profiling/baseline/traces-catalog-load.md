# Decomposition of `GET api/polls` (baseline, load), 900 traces of requests in the window, this script's and k6's

| part | median ms | p95 ms |
|---|---|---|
| whole request (server span) | 34.93 | 53.41 |
| SQL, wall time (shards in parallel) | 34.27 | 52.71 |
| Redis, wall time | 0.00 | 0.00 |
| backend outside SQL and Redis | 0.69 | 1.06 |
| one SQL statement on postgres-replica | 1.55 | 5.55 |
| one SQL statement on postgres-shard-b-replica | 16.39 | 29.43 |

Requests that reached PostgreSQL: 900 of 900; SQL statements per request: 4.0.
An SQL span covers the whole statement round trip (send, parse, plan, execute, receive): the trace cannot split
planning from execution — that split comes from pg_stat_statements.
One full trace: trace-catalog-load.json (open in Jaeger: Search → JSON File).
