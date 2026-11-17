"""Звіт лаби 7, 2.6: Single Node проти двох шардів для кожного режиму scenario-shards.js (write / read / catalog).

По ступенях — RPS, p95 / p99, помилки і середній CPU кожного вузла БД та backend-ів (з …-resources.tsv, які знімає
run.sh); точка насичення — останній ступінь, після якого RPS виріс менше ніж на 10 %. Наприкінці — графіки Mermaid.
  python load-tests/shards-report.py            # бере останні JSON кожної пари з load-tests/results/
Лише стандартна бібліотека Python.
"""
import glob
import json
import sys
from pathlib import Path

RESULTS = Path(__file__).parent / "results"
MODES = {"write": "shard-local write (votes)", "read": "shard-local read (poll details)", "catalog": "fan-out (catalog)"}
NODES = [("A pri", "postgres"), ("A rep", "postgres-replica"), ("B pri", "postgres-shard-b"), ("B rep", "postgres-shard-b-replica")]


def load(topology, mode):
    files = sorted(glob.glob(str(RESULTS / f"scenario-shards-{mode}-{topology}-{mode}-*.json")))
    if not files:
        return None
    data = json.loads(Path(files[-1]).read_text(encoding="utf-8"))
    resources = RESULTS / f"scenario-shards-{topology}-{mode}-resources.tsv"
    samples = []
    if resources.exists():
        for line in resources.read_text(encoding="utf-8").splitlines()[1:]:
            parts = line.split("\t")
            if len(parts) == 4:
                samples.append((int(parts[0]), parts[1], float(parts[2].rstrip("%") or 0)))
    started = data["setup_data"].get("startedAt", 0) / 1000
    schedule = data["schedule"]
    m = data["metrics"]
    steps = sorted(k.split("{scenario:")[1][:-1] for k in m if k.startswith("http_req_duration{scenario:vus_"))
    rows = []
    for i, name in enumerate(steps):
        begin = started + schedule["warmup"] + schedule["gap"] + i * (schedule["step"] + schedule["gap"])
        end = begin + schedule["step"]

        def cpu(service):
            window = [s[2] for s in samples if s[1] == service and begin <= s[0] <= end]
            return sum(window) / len(window) if window else None

        backends = [c for c in (cpu("backend-1"), cpu("backend-2")) if c is not None]
        d = m[f"http_req_duration{{scenario:{name}}}"]["values"]
        rows.append({
            "vus": int(name[4:]),
            "rps": m[f"http_reqs{{scenario:{name}}}"]["values"]["count"] / schedule["step"],
            "p95": d["p(95)"], "p99": d["p(99)"],
            "errors": 100 * m[f"http_req_failed{{scenario:{name}}}"]["values"]["rate"],
            "cpu": {label: cpu(service) for label, service in NODES},
            "backend": sum(backends) / len(backends) if backends else None,
        })
    return rows


def saturation(rows):
    for current, following in zip(rows, rows[1:]):
        if following["rps"] < current["rps"] * 1.1:
            return current
    return None


def f(v, digits=1):
    return "-" if v is None else f"{v:.{digits}f}"


def main():
    results = {}
    for mode, title in MODES.items():
        single, sharded = load("single", mode), load("sharded", mode)
        if not single or not sharded:
            print(f"\n### {title}: no results for both topologies yet")
            continue
        results[mode] = (single, sharded)
        print(f"\n### {title}\n")
        print("| VUs | Single: RPS | p95 / p99, ms | err % | Sharded: RPS | p95 / p99, ms | err % | RPS ×  |")
        print("|---|---|---|---|---|---|---|---|")
        for s, h in zip(single, sharded):
            print(f"| {s['vus']} | {f(s['rps'], 0)} | {f(s['p95'])} / {f(s['p99'])} | {f(s['errors'], 2)} | "
                  f"{f(h['rps'], 0)} | {f(h['p95'])} / {f(h['p99'])} | {f(h['errors'], 2)} | {h['rps'] / s['rps']:.2f} |")
        print("\nCPU %, average over the step (one core per database node; backends 2 cores each, 200 % = full):\n")
        print("| VUs | topology | " + " | ".join(label for label, _ in NODES) + " | backend avg |")
        print("|---|---|" + "---|" * len(NODES) + "---|")
        for s, h in zip(single, sharded):
            for topology, r in (("single", s), ("sharded", h)):
                print(f"| {r['vus']} | {topology} | " + " | ".join(f(r['cpu'][label], 0) for label, _ in NODES)
                      + f" | {f(r['backend'], 0)} |")
        for topology, rows in (("Single", single), ("Sharded", sharded)):
            point = saturation(rows)
            print(f"\n{topology} saturation point: " + (f"{point['vus']} VUs, {point['rps']:.0f} RPS, p95 {point['p95']:.1f} ms"
                                                       if point else "not reached up to the last step"))

    for mode, (single, sharded) in results.items():
        print(f"\n```mermaid\nxychart-beta\n    title \"{MODES[mode]}: RPS, Single (1) vs Sharded (2)\"")
        print(f"    x-axis \"VUs\" [{', '.join(str(r['vus']) for r in single)}]")
        print("    y-axis \"RPS\"")
        for rows in (single, sharded):
            values = ", ".join(str(round(r["rps"])) for r in rows)
            print(f"    bar [{values}]")
        print("```")


if __name__ == "__main__":
    sys.exit(main())
