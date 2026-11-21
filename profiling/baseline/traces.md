# Catalog request decomposition (baseline), 300 traces, sequential requests

| part | median ms | p95 ms |
|---|---|---|
| whole request (server span) | 8.03 | 11.73 |
| SQL, wall time (both shards in parallel) | 5.11 | 7.12 |
| backend outside SQL (routing, EF, merge, JSON) | 2.87 | 4.31 |
| one SQL statement on postgres-replica | 1.76 | 2.55 |
| one SQL statement on postgres-shard-b-replica | 1.69 | 2.49 |

SQL statements per request: 4.0.
One full trace: trace-example.json (open in Jaeger: Search → JSON File).
