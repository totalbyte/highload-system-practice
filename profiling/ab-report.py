"""Звіт A/B лаби 9 (пункт 2.4): прогони profiling/ab-series.sh (сирі зведення k6 і заміри ресурсів — profiling/ab-results/)
→ profiling/ab-report.md.

Для кожного режиму (catalog, write, read) і ступеня: середнє по повторах RPS, p95, p99, помилки, CPU кожного вузла БД
і backend-ів, пам'ять backend-ів; дельта «після» відносно «до». Точка насичення — останній ступінь, після якого RPS
виріс менше ніж на 10 %. Наприкінці — графік Mermaid. Лише стандартна бібліотека Python.
  python profiling/ab-report.py
"""
import glob
import json
import re
import sys
from pathlib import Path

# Сирі результати лежать у репозиторії (ab-series.sh копіює їх сюди): звіт можна перевірити без 40-хвилинного прогону.
RESULTS = Path(__file__).parent / "ab-results"
OUT = Path(__file__).parent / "ab-report.md"
NODES = [("A pri", "postgres"), ("A rep", "postgres-replica"), ("B pri", "postgres-shard-b"), ("B rep", "postgres-shard-b-replica")]
TITLES = {"catalog": "Каталог (fan-out, симптом лаби 9)", "write": "Регресія: запис голосів (Primary шардів)",
          "read": "Регресія: деталі опитування (репліки, shard-local)"}


def mem_mib(text):
    used = text.split("/")[0].strip()
    number = float(re.sub(r"[^0-9.]", "", used) or 0)
    return number * 1024 if used.endswith("GiB") else number


def one_run(mode, tag):
    files = sorted(glob.glob(str(RESULTS / f"scenario-shards-{mode}-{tag}-*.json")))
    if not files:
        return None
    data = json.loads(Path(files[-1]).read_text(encoding="utf-8"))
    samples = []
    resources = RESULTS / f"scenario-shards-{tag}-resources.tsv"
    if resources.exists():
        for line in resources.read_text(encoding="utf-8").splitlines()[1:]:
            p = line.split("\t")
            if len(p) == 4:
                samples.append((int(p[0]), p[1], float(p[2].rstrip("%") or 0), mem_mib(p[3])))
    started, sched, m = data["setup_data"].get("startedAt", 0) / 1000, data["schedule"], data["metrics"]
    steps = sorted(k.split("{scenario:")[1][:-1] for k in m if k.startswith("http_req_duration{scenario:vus_"))
    rows = {}
    for i, name in enumerate(steps):
        begin = started + sched["warmup"] + sched["gap"] + i * (sched["step"] + sched["gap"])
        end = begin + sched["step"]

        # docker stats з усіма контейнерами відповідає ≈ 13 с, тож на 30-секундний ступінь лише 2–3 заміри. Заміри біля
        # країв ступеня можуть захопити паузу між ступенями — беремо лише ті, що всередині, з відступом 3 с.
        def inside(service):
            return [s for s in samples if s[1] == service and begin + 3 <= s[0] <= end - 1]

        def avg(service, field):
            values = [s[field] for s in inside(service)]
            return sum(values) / len(values) if values else None

        d = m[f"http_req_duration{{scenario:{name}}}"]["values"]
        backends = [v for v in (avg("backend-1", 2), avg("backend-2", 2)) if v is not None]
        memory = [v for v in (avg("backend-1", 3), avg("backend-2", 3)) if v is not None]
        rows[int(name[4:])] = {
            "rps": m[f"http_reqs{{scenario:{name}}}"]["values"]["count"] / sched["step"],
            "p95": d["p(95)"], "p99": d["p(99)"],
            "errors": 100 * m[f"http_req_failed{{scenario:{name}}}"]["values"]["rate"],
            "cpu": {label: avg(service, 2) for label, service in NODES},
            "backend": sum(backends) / len(backends) if backends else None,
            "memory": sum(memory) / len(memory) if memory else None,
            "cpu_samples": len(inside("postgres-replica")),
        }
    return rows


def mean_runs(runs):
    """Середнє по повторах для кожного ступеня; None — якщо прогону немає."""
    runs = [r for r in runs if r]
    if not runs:
        return None
    result = {}
    for vus in runs[0]:
        group = [r[vus] for r in runs if vus in r]
        mean = lambda key: sum(g[key] for g in group if g[key] is not None) / max(1, sum(1 for g in group if g[key] is not None))
        result[vus] = {key: mean(key) for key in ("rps", "p95", "p99", "errors", "backend", "memory")}
        result[vus]["cpu"] = {label: mean_of([g["cpu"][label] for g in group]) for label, _ in NODES}
        result[vus]["spread"] = (min(g["rps"] for g in group), max(g["rps"] for g in group))
        result[vus]["n"] = len(group)
        result[vus]["cpu_samples"] = sum(g["cpu_samples"] for g in group)
    return result


def mean_of(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def delta(before, after):
    return f"{100 * (after - before) / before:+.1f} %" if before else "-"


def saturation(rows):
    keys = sorted(rows)
    for current, following in zip(keys, keys[1:]):
        if rows[following]["rps"] < rows[current]["rps"] * 1.1:
            return current, rows[current]
    return None


def f(v, digits=1):
    return "-" if v is None else f"{v:.{digits}f}"


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    lines = ["# Лабораторна 9: A/B — до і після `Max Auto Prepare`", "",
             "Згенеровано `profiling/ab-report.py` з прогонів `profiling/ab-series.sh`. «До» — `DB_MAX_AUTO_PREPARE=0`, "
             "«після» — `20`. Кожна комірка — середнє по повторах; стенд — одне ядро на вузол БД. Каталог — 3 повтори кожної "
             "конфігурації через один, регресія запису й читання — по одному прогону, тож її числа менш надійні.", "",
             "«Δ RPS, межі» — найгірший і найкращий випадок з окремих повторів: (мінімум «після» − максимум «до») / максимум «до» "
             "і (максимум «після» − мінімум «до») / мінімум «до». Якщо нижня межа вище нуля, ефект більший за розкид між повторами.", ""]
    charts = []
    for mode, title in TITLES.items():
        repeats = sorted({int(x) for x in re.findall(rf"scenario-shards-{mode}-ab-before-{mode}-(\d+)-",
                                                     " ".join(glob.glob(str(RESULTS / "*.json"))))})
        before = mean_runs([one_run(mode, f"ab-before-{mode}-{r}") for r in repeats])
        after = mean_runs([one_run(mode, f"ab-after-{mode}-{r}") for r in repeats])
        if not before or not after:
            continue
        n = max(v["n"] for v in before.values())
        lines += [f"## {title}", "", f"Повторів кожної конфігурації: {n}.", "",
                  "| VUs | RPS до (min–max) | RPS після (min–max) | Δ RPS | Δ RPS, межі | p95 до / після, мс | Δ p95 | p99 до / після, мс | Δ p99 | помилки до / після, % |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
        for vus in sorted(before):
            b, a = before[vus], after.get(vus)
            if not a:
                continue
            (b_lo, b_hi), (a_lo, a_hi) = b["spread"], a["spread"]
            lines.append(f"| {vus} | {f(b['rps'], 0)} ({b_lo:.0f}–{b_hi:.0f}) | {f(a['rps'], 0)} ({a_lo:.0f}–{a_hi:.0f}) | "
                         f"{delta(b['rps'], a['rps'])} | {delta(b_hi, a_lo)} … {delta(b_lo, a_hi)} | "
                         f"{f(b['p95'])} / {f(a['p95'])} | {delta(b['p95'], a['p95'])} | {f(b['p99'])} / {f(a['p99'])} | "
                         f"{delta(b['p99'], a['p99'])} | {f(b['errors'], 2)} / {f(a['errors'], 2)} |")
        lines += ["", "CPU, % одного ядра (вузли БД обмежені одним ядром, backend — двома, тобто 200 % = повністю), пам'ять backend. "
                  "`docker stats` дає замір раз на ≈ 13 с, тож на ступінь припадає 1–3 заміри на прогін (стовпець «замірів CPU» — "
                  "сума по повторах): CPU показує, чи вузол на стелі, але не точний відсоток.", "",
                  "| VUs | конфігурація | " + " | ".join(l for l, _ in NODES) + " | backend CPU | backend RAM, МіБ | замірів CPU |",
                  "|---|---|" + "---|" * len(NODES) + "---|---|---|"]
        for vus in sorted(before):
            for label, r in (("до", before[vus]), ("після", after.get(vus))):
                if r:
                    lines.append(f"| {vus} | {label} | " + " | ".join(f(r["cpu"][l], 0) for l, _ in NODES)
                                 + f" | {f(r['backend'], 0)} | {f(r['memory'], 0)} | {r['cpu_samples']} |")
        for label, rows in (("До", before), ("Після", after)):
            point = saturation(rows)
            lines.append("" if label == "До" else "")
            lines.append(f"{label}: точка насичення — " + (f"{point[0]} VU, {point[1]['rps']:.0f} RPS, p95 {point[1]['p95']:.1f} мс"
                                                           if point else "не досягнуто до останнього ступеня"))
        lines.append("")
        vus = sorted(before)
        # Дві лінії з явними кольорами: два ряди стовпчиків xychart малює один поверх одного, і вищий закриває нижчий.
        top = max(r["rps"] for r in list(before.values()) + list(after.values()))
        charts += ["```mermaid", '%%{init: {"themeVariables": {"xyChart": {"plotColorPalette": "#dc2626, #2563eb"}}}}%%',
                   "xychart-beta", f"    title \"{title}, RPS. Червона — до, синя — після\"",
                   f"    x-axis \"VUs\" [{', '.join(map(str, vus))}]", f"    y-axis \"RPS\" 0 --> {int(top * 1.15 / 100 + 1) * 100}",
                   "    line [" + ", ".join(str(round(before[v]["rps"])) for v in vus) + "]",
                   "    line [" + ", ".join(str(round(after[v]["rps"])) for v in vus if v in after) + "]", "```", ""]
    text = "\n".join(lines + charts)
    OUT.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
