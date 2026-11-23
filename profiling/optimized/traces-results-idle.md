# Decomposition of `GET api/polls/{id:long}/results` (optimized, idle), 300 traces of sequential requests

| part | median ms | p95 ms |
|---|---|---|
| whole request (server span) | 0.86 | 3.86 |
| SQL, wall time (shards in parallel) | 0.00 | 0.81 |
| Redis, wall time | 0.37 | 1.58 |
| backend outside SQL and Redis | 0.49 | 1.41 |
| one SQL statement on postgres | 1.16 | 1.80 |
| one SQL statement on postgres-shard-b | 0.83 | 3.09 |

Requests that reached PostgreSQL: 20 of 300; SQL statements per request: 0.1.
An SQL span covers the whole statement round trip (send, parse, plan, execute, receive): the trace cannot split
planning from execution — that split comes from pg_stat_statements.
One full trace: trace-results-idle.json (open in Jaeger: Search → JSON File).
