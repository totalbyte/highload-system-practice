# Decomposition of `GET api/polls` (optimized, idle), 300 traces of sequential requests

| part | median ms | p95 ms |
|---|---|---|
| whole request (server span) | 3.52 | 4.82 |
| SQL, wall time (shards in parallel) | 1.81 | 2.65 |
| Redis, wall time | 0.00 | 0.00 |
| backend outside SQL and Redis | 1.60 | 2.51 |
| one SQL statement on postgres-replica | 0.53 | 1.07 |
| one SQL statement on postgres-shard-b-replica | 0.55 | 1.05 |

Requests that reached PostgreSQL: 300 of 300; SQL statements per request: 4.0.
An SQL span covers the whole statement round trip (send, parse, plan, execute, receive): the trace cannot split
planning from execution — that split comes from pg_stat_statements.
One full trace: trace-catalog-idle.json (open in Jaeger: Search → JSON File).
