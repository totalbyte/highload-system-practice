"""Звіт Hot Shard (лаба 7, 2.3): для кожного прогону scenario-hot-shard — по ступенях RPS, p95 / p99 кожного шарду,
частка запитів і середній CPU / пам'ять Primary кожного шарду (з …-resources.tsv, які знімає run.sh).

  python load-tests/hot-shard-report.py "Range=load-tests/results/scenario-hot-shard-range-*.json" "Buckets=..."

Мітка перед «=» — назва стовпця. Друкує таблиці й графік Mermaid (xychart) p95 до / після. Лише стандартна бібліотека.
"""
import glob
import json
import sys
from pathlib import Path

PRIMARIES = {"A": "postgres", "B": "postgres-shard-b"}


def load(pattern):
    """Останній JSON k6 за шаблоном і файл ресурсів тієї ж мітки: scenario-hot-shard-<мітка>-resources.tsv."""
    path = sorted(glob.glob(pattern))[-1]
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    started = data["setup_data"].get("startedAt", 0) / 1000
    resources = Path(pattern.replace("-*.json", "-resources.tsv"))
    return path, data, started, resources if resources.exists() else None


def mem_mib(text):
    used = text.split("/")[0].strip()
    value = float("".join(c for c in used if c.isdigit() or c == "."))
    return value * 1024 if used.endswith("GiB") else value


def steps(data):
    names = sorted(k.split("{scenario:")[1][:-1] for k in data["metrics"]
                   if k.startswith("http_req_duration{scenario:vus_"))
    return names


def report(label, pattern):
    path, data, started, resources = load(pattern)
    schedule = data["schedule"]
    rows = []
    samples = []
    if resources:
        for line in resources.read_text(encoding="utf-8").splitlines()[1:]:
            parts = line.split("\t")
            if len(parts) == 4:
                samples.append((int(parts[0]), parts[1], float(parts[2].rstrip("%") or 0), mem_mib(parts[3])))
    for i, name in enumerate(steps(data)):
        m = data["metrics"]
        begin = started + schedule["warmup"] + schedule["gap"] + i * (schedule["step"] + schedule["gap"])
        end = begin + schedule["step"]
        row = {"step": name, "vus": int(name[4:]),
               "rps": m[f"http_reqs{{scenario:{name}}}"]["values"]["count"] / schedule["step"],
               "p95": m[f"http_req_duration{{scenario:{name}}}"]["values"]["p(95)"],
               "errors": 100 * m[f"http_req_failed{{scenario:{name}}}"]["values"]["rate"]}
        total = sum(m.get(f"shard_{s}_requests{{scenario:{name}}}", {}).get("values", {}).get("count", 0) for s in "AB")
        for shard, service in PRIMARIES.items():
            values = m.get(f"shard_{shard}_duration{{scenario:{name}}}", {}).get("values", {})
            count = m.get(f"shard_{shard}_requests{{scenario:{name}}}", {}).get("values", {}).get("count", 0)
            window = [s for s in samples if s[1] == service and begin <= s[0] <= end]
            row[shard] = {
                "share": 100 * count / total if total else 0,
                "p95": values.get("p(95)"), "p99": values.get("p(99)"),
                "cpu": sum(s[2] for s in window) / len(window) if window else None,
                "mem": max((s[3] for s in window), default=None),
            }
        rows.append(row)

    print(f"\n### {label}  ({Path(path).name})\n")
    print("| VUs | RPS | p95 ms | errors % | A: share % | A: p95 / p99 ms | A: CPU % | A: RAM MiB | B: share % | B: p95 / p99 ms | B: CPU % | B: RAM MiB |")
    print("|---|---|---|---|---|---|---|---|---|---|---|---|")
    f = lambda v, d=1: "-" if v is None else f"{v:.{d}f}"
    for r in rows:
        cells = [str(r["vus"]), f(r["rps"], 0), f(r["p95"]), f(r["errors"], 2)]
        for shard in "AB":
            s = r[shard]
            cells += [f(s["share"]), f"{f(s['p95'])} / {f(s['p99'])}", f(s["cpu"], 0), f(s["mem"], 0)]
        print("| " + " | ".join(cells) + " |")
    return rows


def main():
    runs = [arg.split("=", 1) for arg in sys.argv[1:]]
    if not runs:
        sys.exit(__doc__)
    results = {label: report(label, pattern) for label, pattern in runs}

    labels = list(results)
    vus = [r["vus"] for r in results[labels[0]]]
    print("\n```mermaid\nxychart-beta\n    title \"p95, ms: hottest shard of each run\"")
    print(f"    x-axis \"VUs\" [{', '.join(map(str, vus))}]")
    print("    y-axis \"p95, ms\"")
    for label in labels:
        hottest = [max((r[s]["p95"] or 0) for s in "AB") for r in results[label]]
        print(f"    line [{', '.join(f'{v:.0f}' for v in hottest)}]")
    print("```")
    print("Lines in the order: " + ", ".join(labels))


if __name__ == "__main__":
    main()
