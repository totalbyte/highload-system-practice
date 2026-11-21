"""Декомпозиція запиту каталогу за трасами Jaeger (лаба 9, ADR 0066): скільки з загального часу відповіді займають
SQL-запити кожного шарду і скільки — сам backend.

Скрипт сам шле N запитів каталогу через HAProxy (стек піднято з TRACING_ENABLED=true і профілем tracing), потім забирає
траси з Jaeger і рахує по них: загальний час серверного спану, час SQL-спанів по вузлах (паралельні запити до шардів
перекриваються, тому окремо — «стіна» SQL, тобто об'єднання інтервалів) і решту — backend.

  python profiling/traces.py profiling/baseline [--requests 200]
Пише traces.md і один приклад траси trace-example.json у теку. Лише стандартна бібліотека Python.
"""
import argparse
import http.client
import json
import statistics
import sys
import time
import urllib.request
from pathlib import Path

API = ("127.0.0.1", 8080)
JAEGER = "http://127.0.0.1:16686"
PATH = "/api/polls?status=active&pageSize=20"


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


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("folder")
    parser.add_argument("--requests", type=int, default=200)
    args = parser.parse_args()
    folder = Path(args.folder)

    connection = http.client.HTTPConnection(*API, timeout=30)
    started = int(time.time() * 1_000_000)
    for _ in range(args.requests):
        connection.request("GET", PATH)
        connection.getresponse().read()
    time.sleep(6)  # експортер відправляє спани пачками раз на кілька секунд

    url = (f"{JAEGER}/api/traces?service=polling-api&operation=GET%20api%2Fpolls&limit={args.requests * 2}"
           f"&start={started}&end={int(time.time() * 1_000_000)}")
    traces = json.load(urllib.request.urlopen(url, timeout=30))["data"]

    totals, sql_wall, sql_by_node, other = [], [], {}, []
    for trace in traces:
        spans = trace["spans"]
        root = next((s for s in spans if s["operationName"] == "GET api/polls"), None)
        if root is None:
            continue
        db = [s for s in spans if tag(s, "db.system", "db.system.name") == "postgresql"]
        wall = union((s["startTime"], s["startTime"] + s["duration"]) for s in db)
        totals.append(root["duration"] / 1000)
        sql_wall.append(wall / 1000)
        other.append((root["duration"] - wall) / 1000)
        for s in db:
            node = tag(s, "server.address", "net.peer.name") or "?"
            sql_by_node.setdefault(node, []).append(s["duration"] / 1000)

    if not totals:
        sys.exit("no catalog traces found: is the stack up with TRACING_ENABLED=true and the tracing profile?")
    json.dump(traces[0], open(folder / "trace-example.json", "w", encoding="utf-8"), indent=1)

    med = statistics.median
    lines = [f"# Catalog request decomposition ({folder.name}), {len(totals)} traces, sequential requests", "",
             "| part | median ms | p95 ms |", "|---|---|---|",
             f"| whole request (server span) | {med(totals):.2f} | {statistics.quantiles(totals, n=20)[18]:.2f} |",
             f"| SQL, wall time (both shards in parallel) | {med(sql_wall):.2f} | {statistics.quantiles(sql_wall, n=20)[18]:.2f} |",
             f"| backend outside SQL (routing, EF, merge, JSON) | {med(other):.2f} | {statistics.quantiles(other, n=20)[18]:.2f} |"]
    for node, values in sorted(sql_by_node.items()):
        lines.append(f"| one SQL statement on {node} | {med(values):.2f} | {statistics.quantiles(values, n=20)[18]:.2f} |")
    lines += ["", f"SQL statements per request: {sum(len(v) for v in sql_by_node.values()) / len(totals):.1f}.",
              "One full trace: trace-example.json (open in Jaeger: Search → JSON File)."]
    text = "\n".join(lines)
    (folder / "traces.md").write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
