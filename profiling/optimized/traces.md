# Catalog request decomposition (optimized), 300 traces, sequential requests

| part | median ms | p95 ms |
|---|---|---|
| whole request (server span) | 7.21 | 9.52 |
| SQL, wall time (both shards in parallel) | 4.25 | 5.76 |
| backend outside SQL (routing, EF, merge, JSON) | 2.92 | 4.53 |
| one SQL statement on postgres-replica | 1.34 | 1.88 |
| one SQL statement on postgres-shard-b-replica | 1.34 | 2.04 |

SQL statements per request: 4.0.
One full trace: trace-example.json (open in Jaeger: Search → JSON File).
