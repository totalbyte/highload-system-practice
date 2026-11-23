"""Декомпозиція запиту за трасами Jaeger (лаба 9, ADR 0066): скільки з загального часу відповіді займають SQL (кожен шард),
кеш Redis і сам backend.

Скрипт сам шле N запитів через HAProxy (стек піднято з TRACING_ENABLED=true і профілем tracing), потім забирає їхні траси
з Jaeger і рахує загальний час серверного спану, «стіну» SQL (паралельні запити до шардів перекриваються, тому —
об'єднання інтервалів), час команд Redis і решту — backend. Якщо одночасно йде навантаження k6, траса показує, як ці
частини поводяться під ним.

  python profiling/traces.py profiling/baseline [--kind catalog|results] [--requests 200] [--label idle]
  catalog  — GET /api/polls?status=active&pageSize=20 (fan-out, кеш не використовує);
  results  — GET /api/polls/{id}/results (shard-local, Cache-Aside у Redis з лаби 4).
Пише traces-<kind>-<label>.md і один приклад траси trace-<kind>-<label>.json у теку. Лише стандартна бібліотека Python.
"""
import argparse
import http.client
import json
import statistics
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

API = ("127.0.0.1", 8080)
JAEGER = "http://127.0.0.1:16686"
KINDS = {
    "catalog": ("/api/polls?status=active&pageSize=20", "GET api/polls"),
    "results": ("/api/polls/{id}/results", "GET api/polls/{id:long}/results"),
}


def tag(span, *keys):
    for t in span.get("tags", []):
        if t["key"] in keys:
            return t["value"]
    return None


def union(intervals):
    """Сумарна довжина об'єднання інтервалів: паралельні SQL двох шардів рахуються один раз."""
    total, end = 0, None
    for start, stop in sorted(intervals):
        if end is None or start > end:
            total += stop - start
            end = stop
        elif stop > end:
            total += stop - end
            end = stop
    return total


def p95(values):
    return statistics.quantiles(values, n=20)[18] if len(values) >= 20 else max(values)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("folder")
    parser.add_argument("--kind", choices=sorted(KINDS), default="catalog")
    parser.add_argument("--requests", type=int, default=200)
    parser.add_argument("--label", default="idle", help="idle / load: is k6 running at the same time")
    args = parser.parse_args()
    folder = Path(args.folder)
    path, operation = KINDS[args.kind]

    connection = http.client.HTTPConnection(*API, timeout=30)
    if args.kind == "results":
        # Результати різних опитувань: частина читань — HIT у Redis, частина — MISS і запит до БД.
        connection.request("GET", "/api/polls?status=active&pageSize=20")
        ids = [p["id"] for p in json.loads(connection.getresponse().read())["items"]]
    started = int(time.time() * 1_000_000)
    for i in range(args.requests):
        connection.request("GET", path.replace("{id}", str(ids[i % len(ids)])) if args.kind == "results" else path)
        connection.getresponse().read()
    time.sleep(6)  # експортер відправляє спани пачками раз на кілька секунд

    url = (f"{JAEGER}/api/traces?service=polling-api&operation={urllib.parse.quote(operation)}&limit={args.requests * 3}"
           f"&start={started}&end={int(time.time() * 1_000_000)}")
    traces = json.load(urllib.request.urlopen(url, timeout=30))["data"]

    totals, sql_wall, redis_wall, other, sql_by_node, statements = [], [], [], [], {}, []
    for trace in traces:
        spans = trace["spans"]
        root = next((s for s in spans if s["operationName"] == operation), None)
        if root is None:
            continue
        db = [s for s in spans if tag(s, "db.system", "db.system.name") == "postgresql"]
        cache = [s for s in spans if tag(s, "db.system", "db.system.name") == "redis"]
        sql = union((s["startTime"], s["startTime"] + s["duration"]) for s in db)
        red = union((s["startTime"], s["startTime"] + s["duration"]) for s in cache)
        totals.append(root["duration"] / 1000)
        sql_wall.append(sql / 1000)
        redis_wall.append(red / 1000)
        other.append((root["duration"] - sql - red) / 1000)
        statements.append(len(db))
        for s in db:
            node = tag(s, "server.address", "net.peer.name") or "?"
            sql_by_node.setdefault(node, []).append(s["duration"] / 1000)

    if not totals:
        sys.exit("no traces found: is the stack up with TRACING_ENABLED=true and the tracing profile?")
    name = f"{args.kind}-{args.label}"
    json.dump(traces[0], open(folder / f"trace-{name}.json", "w", encoding="utf-8"), indent=1)

    med = statistics.median
    # Під навантаженням Jaeger віддає й траси запитів самого k6 з того самого вікна — це теж вибірка «під навантаженням».
    source = "sequential requests of this script" if args.label == "idle" else "requests in the window, this script's and k6's"
    lines = [f"# Decomposition of `{operation}` ({folder.name}, {args.label}), {len(totals)} traces of {source}", "",
             "| part | median ms | p95 ms |", "|---|---|---|",
             f"| whole request (server span) | {med(totals):.2f} | {p95(totals):.2f} |",
             f"| SQL, wall time (shards in parallel) | {med(sql_wall):.2f} | {p95(sql_wall):.2f} |",
             f"| Redis, wall time | {med(redis_wall):.2f} | {p95(redis_wall):.2f} |",
             f"| backend outside SQL and Redis | {med(other):.2f} | {p95(other):.2f} |"]
    for node, values in sorted(sql_by_node.items()):
        lines.append(f"| one SQL statement on {node} | {med(values):.2f} | {p95(values):.2f} |")
    with_sql = sum(1 for n in statements if n)
    lines += ["", f"Requests that reached PostgreSQL: {with_sql} of {len(totals)}; SQL statements per request: "
                  f"{sum(statements) / len(totals):.1f}.",
              "An SQL span covers the whole statement round trip (send, parse, plan, execute, receive): the trace cannot split",
              "planning from execution — that split comes from pg_stat_statements.",
              f"One full trace: trace-{name}.json (open in Jaeger: Search → JSON File)."]
    text = "\n".join(lines)
    (folder / f"traces-{name}.md").write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
