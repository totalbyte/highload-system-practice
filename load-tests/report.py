"""Звіт за результатами k6 (лаба 5): таблиці по ступенях, ресурси по ступенях, графіки Mermaid.

  python load-tests/report.py load-tests/results/scenario-a-read-baseline-*.json
  python load-tests/report.py --compare 1-inst=a1.json 2-inst=a2.json 3-inst=a3.json     # серії поруч

Для кожного JSON шукає поруч файли ресурсів з run.sh (<сценарій>-<мітка>-resources.tsv / -db.tsv) і, якщо в них є
стовпець epoch_s, усереднює CPU контейнерів і стан сесій PostgreSQL окремо по кожному ступеню.
Вивід — Markdown у stdout (вставляється в README як є). Лише стандартна бібліотека.
"""
import csv
import json
import os
import re
import sys
from collections import defaultdict


def load(path):
    with open(path, encoding="utf8") as f:
        data = json.load(f)
    steps = []
    for key, metric in data["metrics"].items():
        m = re.fullmatch(r"http_req_duration\{scenario:(.+)\}", key)
        if not m:
            continue
        name = m.group(1)
        values = metric["values"]
        reqs = data["metrics"][f"http_reqs{{scenario:{name}}}"]["values"]["count"]
        failed = data["metrics"][f"http_req_failed{{scenario:{name}}}"]["values"]["rate"]
        steps.append({"name": name, "vus": None if name == "warmup" else int(name[4:]), "reqs": reqs,
                      "failed": failed, **{k: values.get(k) for k in ("avg", "med", "p(95)", "p(99)", "max")}})
    schedule = data.get("schedule", {"step": 40, "warmup": 20, "gap": 5})
    for s in steps:
        s["seconds"] = schedule["warmup"] if s["vus"] is None else schedule["step"]
        s["rps"] = s["reqs"] / s["seconds"]
    steps.sort(key=lambda s: -1 if s["vus"] is None else s["vus"])
    windows = {}
    started = (data.get("setup_data") or {}).get("startedAt")
    if started:
        t = started / 1000
        windows["warmup"] = (t, t + schedule["warmup"])
        t += schedule["warmup"] + schedule["gap"]
        for s in steps:
            if s["vus"] is not None:
                windows[s["name"]] = (t, t + schedule["step"])
                t += schedule["step"] + schedule["gap"]
    return steps, windows


def resources(json_path, windows):
    """CPU контейнерів і сесії PostgreSQL, усереднені по вікну кожного ступеня (лише для файлів з epoch_s)."""
    prefix = re.sub(r"-\d{4}-\d\d-\d\dT[\d-]+Z\.json$", "", json_path)
    cpu, db = defaultdict(lambda: defaultdict(list)), defaultdict(lambda: defaultdict(list))
    for kind, target in (("resources", cpu), ("db", db)):
        path = f"{prefix}-{kind}.tsv"
        if not os.path.exists(path):
            return None, None
        with open(path, encoding="utf8") as f:
            rows = list(csv.DictReader(f, delimiter="\t"))
        if not rows or "epoch_s" not in rows[0]:
            return None, None
        for row in rows:
            t = float(row["epoch_s"])
            step = next((n for n, (a, b) in windows.items() if a + 3 <= t <= b), None)   # 3 с на вихід на плато
            if step is None:
                continue
            if kind == "resources":
                target[step][row["container"]].append(float(row["cpu_pct"].rstrip("%")))
            else:
                for k in ("active", "waiting_lock", "client_conns", "idle_in_tx"):
                    if row.get(k):
                        target[step][k].append(float(row[k]))
                if row.get("xact_total"):
                    target[step]["xact"].append((t, float(row["xact_total"])))
    avg = lambda xs: sum(xs) / len(xs) if xs else None
    db_out = {}
    for s, d in db.items():
        db_out[s] = {k: avg(v) for k, v in d.items() if k != "xact"}
        points = d.get("xact", [])
        # Транзакцій PostgreSQL за секунду: приріст накопиченого лічильника між першим і останнім зняттям на плато.
        db_out[s]["tps"] = ((points[-1][1] - points[0][1]) / (points[-1][0] - points[0][0])
                            if len(points) >= 2 and points[-1][0] > points[0][0] else None)
    return {s: {c: avg(v) for c, v in d.items()} for s, d in cpu.items()}, db_out


def fmt(v, digits=1):
    return "—" if v is None else f"{v:.{digits}f}"


def step_table(steps):
    out = ["| VUs | Throughput, RPS | Avg, мс | p50, мс | p95, мс | p99, мс | Max, мс | Error rate, % |",
           "|---|---|---|---|---|---|---|---|"]
    for s in steps:
        label = "warm-up" if s["vus"] is None else str(s["vus"])
        out.append(f"| {label} | {s['rps']:.0f} | {fmt(s['avg'])} | {fmt(s['med'])} | {fmt(s['p(95)'])} | "
                   f"{fmt(s['p(99)'])} | {fmt(s['max'])} | {s['failed'] * 100:.2f} |")
    return "\n".join(out)


def resource_table(steps, cpu, db):
    containers = sorted({c for d in cpu.values() for c in d})
    head = ("| VUs | " + " | ".join(f"CPU {c}, %" for c in containers) +
            " | PG транзакцій/с | PG active | PG wait Lock | PG idle in tx | PG conns |")
    out = [head, "|" + "---|" * (len(containers) + 6)]
    for s in steps:
        if s["vus"] is None or s["name"] not in cpu:
            continue
        c, d = cpu[s["name"]], db.get(s["name"], {})
        out.append(f"| {s['vus']} | " + " | ".join(fmt(c.get(x), 0) for x in containers) +
                   f" | {fmt(d.get('tps'), 0)} | {fmt(d.get('active'))} | {fmt(d.get('waiting_lock'))} | "
                   f"{fmt(d.get('idle_in_tx'))} | {fmt(d.get('client_conns'), 0)} |")
    return "\n".join(out)


def chart(title, steps_by_series, field, y_label):
    """Mermaid xychart-beta: вісь X — VUs, по лінії на серію."""
    vus = [s["vus"] for s in next(iter(steps_by_series.values())) if s["vus"] is not None]
    lines = ["```mermaid", "xychart-beta", f'    title "{title}"', f"    x-axis \"VUs\" [{', '.join(map(str, vus))}]",
             f'    y-axis "{y_label}"']
    for steps in steps_by_series.values():
        values = [s[field] for s in steps if s["vus"] is not None]
        lines.append(f"    line [{', '.join(f'{v:.0f}' if v and v >= 10 else f'{(v or 0):.1f}' for v in values)}]")
    lines.append("```")
    return "\n".join(lines)


def main(argv):
    if argv and argv[0] == "--compare":
        series = dict(arg.split("=", 1) for arg in argv[1:])
        loaded = {label: load(path)[0] for label, path in series.items()}
        labels = list(loaded)
        vus = [s["vus"] for s in loaded[labels[0]] if s["vus"] is not None]
        print("| VUs | " + " | ".join(f"{l}: RPS · p95 · p99 мс · err %" for l in labels) + " |")
        print("|---|" + "---|" * len(labels))
        for v in vus:
            cells = []
            for l in labels:
                s = next((x for x in loaded[l] if x["vus"] == v), None)
                cells.append("—" if s is None else
                             f"{s['rps']:.0f} · {fmt(s['p(95)'])} · {fmt(s['p(99)'])} · {s['failed'] * 100:.2f}")
            print(f"| {v} | " + " | ".join(cells) + " |")
        print("\nСерії на графіках — у порядку: " + ", ".join(labels) + "\n")
        print(chart("Throughput, RPS", loaded, "rps", "RPS"))
        print()
        print(chart("p95 latency, ms", loaded, "p(95)", "ms"))
        return
    for path in argv:
        steps, windows = load(path)
        print(f"#### {os.path.basename(path)}\n")
        print(step_table(steps))
        cpu, db = resources(path, windows) if windows else (None, None)
        if cpu:
            print("\nРесурси, середнє по плато ступеня:\n")
            print(resource_table(steps, cpu, db))
        print()
        print(chart("Throughput, RPS", {"rps": steps}, "rps", "RPS"))
        print()
        print(_latency_chart(steps))
        print()


def _line(steps, field):
    values = [s[field] for s in steps if s["vus"] is not None]
    return f"    line [{', '.join(f'{v:.1f}' for v in values)}]"


def _latency_chart(steps):
    vus = [s["vus"] for s in steps if s["vus"] is not None]
    return "\n".join(["```mermaid", "xychart-beta", '    title "Latency p50 / p95 / p99, ms"',
                      f"    x-axis \"VUs\" [{', '.join(map(str, vus))}]", '    y-axis "ms"',
                      _line(steps, "med"), _line(steps, "p(95)"), _line(steps, "p(99)"), "```"])


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")      # консоль Windows інакше ламає кирилицю в заголовках таблиць
    main(sys.argv[1:])
