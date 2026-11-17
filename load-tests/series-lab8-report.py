"""Звіт серії лаби 8 (series-lab8.sh, ADR 0064): порівняльна матриця 2.7 — медіана і [min–max] повторів.

  python load-tests/series-lab8-report.py

Читає load-tests/results/stampede-summary.tsv, penetration-summary.tsv (рядки дописують stampede.sh і penetration.sh),
JSON k6 кожного прогону і scenario-a-read-lab8-*.json; друкує таблиці Markdown. Лише стандартна бібліотека.
"""
import glob
import json
import os
import statistics
import sys

R = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")


def fmt(values, digits=0, suffix=""):
    """Медіана і [min–max]; один повтор — просто значення."""
    med = statistics.median(values)
    one = lambda v: f"{v:.{digits}f}{suffix}"
    return one(med) if len(values) == 1 or min(values) == max(values) else f"{one(med)} [{one(min(values))}–{one(max(values))}]"


def rows(name):
    path = os.path.join(R, name)
    return [line.rstrip("\n").split("\t") for line in open(path, encoding="utf-8")] if os.path.exists(path) else []


def stampede():
    groups = {}
    for protection, mode, delay, rep, loads, inv, js in rows("stampede-summary.tsv"):
        d = json.load(open(os.path.join(R, js), encoding="utf-8"))
        m = d["metrics"]
        dur = m["http_req_duration{phase:stampede}"]["values"]
        reqs = m["http_reqs{phase:stampede}"]["values"]["count"]
        g = groups.setdefault((mode, int(delay), protection), {"per": [], "rps": [], "p95": [], "p99": [], "err": [], "n": 0})
        g["per"].append(int(loads) / max(int(inv), 1))
        g["rps"].append(reqs / (d["state"]["testRunDurationMs"] / 1000))
        g["p95"].append(dur["p(95)"])
        g["p99"].append(dur["p(99)"])
        g["err"].append(m["http_req_failed{phase:stampede}"]["values"]["rate"] * 100)
        g["n"] += 1
    order = ["None", "SingleFlight", "Lock"]
    for mode, delay, title in (("sustained", 50, "Stampede, sustained 30 с, 500 VU, інвалідація кожні 200 мс, агрегат + 50 мс"),
                               ("sustained", 0, "Stampede, sustained 30 с, 500 VU, інвалідація кожні 200 мс, справжній агрегат"),
                               ("burst", 50, "Stampede, burst: 500 VU одночасно після кожної з 5 інвалідацій, агрегат + 50 мс")):
        present = [p for p in order if (mode, delay, p) in groups]
        if not present:
            continue
        print(f"\n**{title}** (повторів: {groups[(mode, delay, present[0])]['n']})\n")
        print("| Режим | Звернень до БД на інвалідацію | Throughput (RPS) | p95 | p99 | Error Rate |")
        print("|---|---|---|---|---|---|")
        for p in present:
            g = groups[(mode, delay, p)]
            rps = fmt(g["rps"]) if mode == "sustained" else "—"
            print(f"| {p} | {fmt(g['per'], 1)} | {rps} | {fmt(g['p95'], 0, ' мс')} | {fmt(g['p99'], 0, ' мс')} | "
                  f"{fmt(g['err'], 2, ' %')} |")


def penetration():
    groups = {}
    for protection, negative, ids, rep, loads, requests, keys, kib, js in rows("penetration-summary.tsv"):
        d = json.load(open(os.path.join(R, js), encoding="utf-8"))
        g = groups.setdefault((protection, negative), {"share": [], "rps": [], "p95": [], "p99": [], "err": [], "keys": []})
        g["share"].append(100 * int(loads) / max(int(requests), 1))
        g["rps"].append(d["rps"])
        g["p95"].append(d["p95"])
        g["p99"].append(d["p99"])
        g["err"].append(d["errors"] * 100)
        g["keys"].append(int(keys))
    if not groups:
        return
    print("\n**Penetration: 200 VU, 30 с, 100 неіснуючих id по колу, справжній агрегат**\n")
    print("| Режим | Запитів до БД, % від усіх | Throughput (RPS) | p95 | p99 | Error Rate | Ключів у Redis |")
    print("|---|---|---|---|---|---|---|")
    for key, title in ((("None", "false"), "без захисту взагалі"), (("Lock", "false"), "Lock, без негативного кешу"),
                       (("Lock", "true"), "Lock + негативний кеш")):
        if key in groups:
            g = groups[key]
            print(f"| {title} | {fmt(g['share'], 2, ' %')} | {fmt(g['rps'])} | {fmt(g['p95'], 0, ' мс')} | "
                  f"{fmt(g['p99'], 0, ' мс')} | {fmt(g['err'], 2, ' %')} | {fmt(g['keys'])} |")


def scenario_a():
    groups = {}
    for path in sorted(glob.glob(os.path.join(R, "scenario-a-read-lab8-*.json"))):
        cfg = os.path.basename(path).split("-")[4]  # scenario-a-read-lab8-<cfg>-r<rep>-<stamp>.json
        m = json.load(open(path, encoding="utf-8"))["metrics"]
        step = json.load(open(path, encoding="utf-8"))["schedule"]["step"]
        for level in ("vus_050", "vus_200"):
            d = m[f"http_req_duration{{scenario:{level}}}"]["values"]
            g = groups.setdefault((cfg, level), {"rps": [], "p95": [], "p99": [], "err": []})
            g["rps"].append(m[f"http_reqs{{scenario:{level}}}"]["values"]["count"] / step)
            g["p95"].append(d["p(95)"])
            g["p99"].append(d["p(99)"])
            g["err"].append(m[f"http_req_failed{{scenario:{level}}}"]["values"]["rate"] * 100)
    if not groups:
        return
    print("\n**Контроль: сценарій A лаби 5 (60 % результати, 25 % деталі, 15 % каталог), 30 с на ступінь**\n")
    print("| Поведінка | VU | Throughput (RPS) | p95 | p99 | Error Rate |")
    print("|---|---|---|---|---|---|")
    for cfg, title in (("singleflight", "до лаби 8: SingleFlight, без негативного кешу"), ("lock", "лаба 8: Lock + негативний кеш")):
        for level in ("vus_050", "vus_200"):
            if (cfg, level) in groups:
                g = groups[(cfg, level)]
                print(f"| {title} | {int(level[4:])} | {fmt(g['rps'])} | {fmt(g['p95'], 0, ' мс')} | "
                      f"{fmt(g['p99'], 0, ' мс')} | {fmt(g['err'], 2, ' %')} |")


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # підписи українською, консоль Windows — cp1252
    stampede()
    penetration()
    scenario_a()


if __name__ == "__main__":
    main()
