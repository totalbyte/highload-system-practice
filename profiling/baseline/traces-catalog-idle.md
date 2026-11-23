# Decomposition of `GET api/polls` (baseline, idle), 300 traces of sequential requests

| part | median ms | p95 ms |
|---|---|---|
| whole request (server span) | 3.94 | 5.48 |
| SQL, wall time (shards in parallel) | 2.22 | 3.29 |
| Redis, wall time | 0.00 | 0.00 |
| backend outside SQL and Redis | 1.69 | 2.31 |
| one SQL statement on postgres-replica | 0.70 | 1.24 |
| one SQL statement on postgres-shard-b-replica | 0.69 | 1.37 |

Requests that reached PostgreSQL: 300 of 300; SQL statements per request: 4.0.
An SQL span covers the whole statement round trip (send, parse, plan, execute, receive): the trace cannot split
planning from execution — that split comes from pg_stat_statements.
One full trace: trace-catalog-idle.json (open in Jaeger: Search → JSON File).
