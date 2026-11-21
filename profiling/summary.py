"""Зведення доказів одного прогону profiling/collect.sh (лаба 9) у profiling/<мітка>/summary.md.

  python profiling/summary.py profiling/baseline
Читає k6.txt, docker-stats.tsv, counters.csv (dotnet-counters), heap-*.txt (dotnet-gcdump report), cpu.folded (flame graph)
і pg-stat-statements-*.txt. Лише стандартна бібліотека Python.
"""
import csv
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path


def k6(folder):
    for line in (folder / "k6.txt").read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("vus_"):
            p = line.split()
            return {"vus": int(p[1]), "rps": float(p[2]), "p50": float(p[4]), "p95": float(p[5]), "p99": float(p[6]),
                    "errors": float(p[8])}
    return {}


def docker_stats(folder):
    cpu, mem = defaultdict(list), defaultdict(list)
    for row in list(csv.reader((folder / "docker-stats.tsv").open(encoding="utf-8"), delimiter="\t"))[1:]:
        if len(row) != 4:
            continue
        cpu[row[1]].append(float(row[2].rstrip("%") or 0))
        used = row[3].split("/")[0].strip()
        number = float(re.sub(r"[^0-9.]", "", used) or 0)
        mem[row[1]].append(number * 1024 if used.endswith("GiB") else number)
    return {c: (sum(v) / len(v), max(mem[c])) for c, v in cpu.items()}


def counters(folder):
    """Середнє по кожному лічильнику; ключ — назва з тегами (пул з'єднань, покоління GC)."""
    values = defaultdict(list)
    for row in csv.DictReader((folder / "counters.csv").open(encoding="utf-8")):
        try:
            values[row["Counter Name"]].append(float(row["Mean/Increment"]))
        except ValueError:
            pass
    return {k: sum(v) / len(v) for k, v in values.items() if v}


def pick(stats, prefix, *parts):
    return [v for k, v in stats.items() if k.startswith(prefix) and all(p in k for p in parts)]


def heap(folder, name):
    """Перший рядок звіту dotnet-gcdump: «10,201,358  GC Heap bytes» — живі об'єкти купи в момент знімка."""
    text = (folder / name).read_text(encoding="utf-8", errors="replace")
    match = re.search(r"^\s*([\d,]+)\s+GC Heap bytes", text, re.M)
    return int(match.group(1).replace(",", "")) if match else 0


def hot_frames(folder, top=12):
    incl, total = Counter(), 0
    for line in (folder / "cpu.folded").open(encoding="utf-8"):
        stack, value = line.rsplit(" ", 1)
        value = int(value)
        total += value
        seen = set()
        for frame in stack.split(";"):
            name = re.sub(r"\(.*", "", frame.split("!")[-1])[:90]
            if name not in seen:
                seen.add(name)
                incl[name] += value
    keys = ("PollingPlatform", "Npgsql", "EntityFrameworkCore", "Json", "PollGC", "Kestrel")
    return [(n, 100 * v / total) for n, v in incl.most_common(400) if any(k in n for k in keys)][:top]


def main():
    # Консоль Windows (cp1251) не друкує стрілки й інші символи звіту.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    folder = Path(sys.argv[1])
    lines = [f"# Profiling summary: {folder.name}", ""]
    load = k6(folder)
    if load:
        lines += ["## Load (k6, catalog)", "",
                  "| VUs | RPS | p50 ms | p95 ms | p99 ms | errors % |", "|---|---|---|---|---|---|",
                  f"| {load['vus']} | {load['rps']:.0f} | {load['p50']} | {load['p95']} | {load['p99']} | {load['errors']} |", ""]

    lines += ["## Containers (average CPU over the window, max memory)", "", "| container | CPU % | RAM MiB |", "|---|---|---|"]
    for name, (cpu, mem) in sorted(docker_stats(folder).items()):
        lines.append(f"| {name} | {cpu:.0f} | {mem:.0f} |")
    lines.append("")

    c = counters(folder)
    first = lambda xs: xs[0] if xs else float("nan")
    replica_pools = lambda metric, *parts: [v for k, v in c.items() if k.startswith(metric) and "replica" in k
                                            and "Pooling=False" not in k and all(p in k for p in parts)]
    gens = {g: first(pick(c, "dotnet.gc.collections", g)) for g in ("gen0", "gen1", "gen2")}
    lines += ["## backend-1 runtime (dotnet-counters, 30 s average)", "", "| counter | value |", "|---|---|",
              # cpu.time має два ряди, cpu.mode=user і cpu.mode=system: процесор процесу — їхня сума.
              f"| CPU, cores (user + system) | {sum(pick(c, 'dotnet.process.cpu.time')):.2f} |",
              f"| GC pause, % of time | {100 * first(pick(c, 'dotnet.gc.pause.time')):.2f} |",
              f"| allocation rate, MB/s | {first(pick(c, 'dotnet.gc.heap.total_allocated')) / 1e6:.1f} |",
              f"| GC collections / s, gen0 / gen1 / gen2 | {gens['gen0']:.2f} / {gens['gen1']:.2f} / {gens['gen2']:.2f} |",
              f"| thread pool queue length | {first(pick(c, 'dotnet.thread_pool.queue.length')):.1f} |",
              f"| thread pool threads | {first(pick(c, 'dotnet.thread_pool.thread.count')):.0f} |",
              f"| lock contentions / s | {first(pick(c, 'dotnet.monitor.lock_contentions')):.1f} |",
              f"| working set, MB | {first(pick(c, 'dotnet.process.memory.working_set')) / 1e6:.0f} |",
              f"| Npgsql prepared ratio, %, replica pools | {', '.join(f'{v:.0f}' for v in replica_pools('db.client.operation.npgsql.prepared_ratio'))} |",
              f"| Npgsql connections used / idle, replica pools | "
              f"{', '.join(f'{v:.1f}' for v in replica_pools('db.client.connection.count', 'state=used'))} / "
              f"{', '.join(f'{v:.1f}' for v in replica_pools('db.client.connection.count', 'state=idle'))} |",
              f"| Npgsql operation p95, replica pools, ms | "
              f"{', '.join(f'{1000 * v:.1f}' for v in replica_pools('db.client.operation.duration', 'Percentile=95'))} |", ""]

    h1, h2 = heap(folder, "heap-1.txt"), heap(folder, "heap-2.txt")
    lines += ["## Heap (dotnet-gcdump, start vs end of the window)", "",
              f"Live objects: {h1 / 1e6:.1f} MB → {h2 / 1e6:.1f} MB ({100 * (h2 - h1) / h1:+.1f} %).", ""]

    lines += ["## Hot frames (CPU_TIME samples, inclusive)", "", "| frame | % of CPU samples |", "|---|---|"]
    lines += [f"| `{name}` | {share:.1f} |" for name, share in hot_frames(folder)]
    lines.append("")

    for f in sorted(folder.glob("pg-stat-statements-*.txt")):
        lines += [f"## {f.stem}", "", "```", f.read_text(encoding="utf-8").rstrip(), "```", ""]
    text = "\n".join(lines)
    (folder / "summary.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
