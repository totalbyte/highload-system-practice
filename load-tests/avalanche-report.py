"""Звіт Cache Avalanche (лаба 8, ADR 0062): по секундах — запити, промахи, звернення до БД, активні сесії, p95 / max.

  python load-tests/avalanche-report.py load-tests/results/avalanche-jitter0-delay50.json [ще .json ...] [--mermaid]

Поруч із кожним JSON k6 avalanche.sh кладе <прогін>-db-<вузол>.tsv: epoch, накопичене число читань агрегату
(pg_stat_statements), активні клієнтські сесії — щосекунди з Primary кожного шарду. Секунда 0 — кінець прогріву.
--mermaid — графіки xychart для README (по лінії на кожен прогін). Лише стандартна бібліотека.
"""
import glob
import json
import statistics
import sys


def load(path):
    run = json.load(open(path, encoding="utf-8"))
    t0 = run["start"] // 1000
    loads, active = {}, {}
    for tsv in glob.glob(path[:-len(".json")] + "-db-*.tsv"):
        prev = None
        for line in open(tsv, encoding="utf-8"):
            parts = line.strip().split("\t")
            if len(parts) != 3:
                continue
            epoch, calls, sessions = map(int, parts)
            sec = epoch - t0
            if prev is not None and sec >= 0:
                loads[sec] = loads.get(sec, 0) + calls - prev
            active[sec] = active.get(sec, 0) + sessions
            prev = calls
    rows = {r["sec"]: r for r in run["rows"]}
    secs = sorted(rows)
    table = [(s, rows[s]["reqs"], rows[s]["misses"], loads.get(s, 0), active.get(s, 0), rows[s]["p95"], rows[s]["max"])
             for s in secs]
    return run, table


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # підписи графіків українською, консоль Windows — cp1252
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    mermaid = "--mermaid" in sys.argv
    runs = [(p, *load(p)) for p in args]
    for path, run, table in runs:
        print(f"\n{run['tag']}: {run['keys']} keys, {run['vus']} VUs, {run['seconds']} s, "
              f"p95 {run['p95']:.0f} ms, p99 {run['p99']:.0f} ms, errors {run['errors'] * 100:.2f} %")
        print(" sec   reqs  misses  DB loads  active  p95 ms  max ms")
        for s, reqs, miss, loads, act, p95, mx in table:
            print(f"{s:4d} {reqs:6d} {miss:7d} {loads:9d} {act:7d} {p95:7.0f} {mx:7.0f}")
        body = [r for r in table if r[0] >= 5]  # без перших секунд: прогрів пулів і JIT
        per_sec = [r[3] for r in body]
        print(f"  after 5 s: DB loads/s max {max(per_sec)}, median {statistics.median(per_sec):.0f}, "
              f"stdev {statistics.pstdev(per_sec):.0f}; p95 per second max {max(r[5] for r in body):.0f} ms, "
              f"median {statistics.median(r[5] for r in body):.0f} ms; active sessions max {max(r[4] for r in body)}")
    if mermaid and runs:
        secs = [r[0] for r in runs[0][2] if r[0] >= 2]  # секунди 0-1 — прогрів (усі ключі разом), він сплющив би шкалу
        # Числова вісь (min --> max): підписи розставляє сам Mermaid. Список із 58 секунд налазив один на одного.
        # Легенди xychart не має, тож кольори ліній задані явно (і читаються в світлій і темній темі) та названі під графіком.
        palette = ["#e8590c", "#1c7ed6", "#2f9e44", "#ae3ec9"]
        init = ('%%{init: {"themeVariables": {"xyChart": {"plotColorPalette": "'
                + ", ".join(palette[:len(runs)]) + '"}}}}%%')
        for title, col, unit in (("Звернення до БД за секунду", 3, "читань агрегату"), ("p95 за секунду", 5, "мс")):
            print(f"\n```mermaid\n{init}\nxychart-beta\n    title \"{title}\"\n    x-axis \"секунда\" {secs[0]} --> {secs[-1]}"
                  f"\n    y-axis \"{unit}\"")
            for _, run, table in runs:
                by = {r[0]: r[col] for r in table}
                print(f"    line [{', '.join(str(round(by.get(s, 0))) for s in secs)}]")
            print("```")
        names = ["помаранчева", "синя", "зелена", "фіолетова"]
        print("Лінії: " + ", ".join(f"{names[i]} — {run['tag']}" for i, (_, run, _) in enumerate(runs)))


if __name__ == "__main__":
    main()
