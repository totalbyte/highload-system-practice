"""Flame graph (SVG) з профілю dotnet-trace у форматі Speedscope (лаба 9).

dotnet-trace на Linux без прав адміністратора знімає час потоків (thread time, ~100 Гц), а не лише CPU. Кожен стек
закінчується псевдокадром: CPU_TIME — потік виконував керований код, UNMANAGED_CODE_TIME — був у нативному коді, переважно
в очікуванні (семафор пулу потоків, мережа). За замовчуванням лишаються лише CPU_TIME — це наближений on-CPU профіль;
--all лишає все (wall clock). Скільки часу лишилося, пишеться в заголовку. Кадри процесу й потоків прибираються, тож
однакові стеки з різних потоків зливаються.

  python profiling/flamegraph.py profile.speedscope.json out.svg [--title "..."] [--all] [--folded out.folded]
Лише стандартна бібліотека Python.
"""
import argparse
import html
import json
import re
from collections import defaultdict

# Службові кадри TraceEvent: процес, «Threads», конкретний потік — не код, лише групування.
SERVICE = re.compile(r"^(Process64 |Process32 |\(Non-Activities\)$|Threads$|Thread \()")


def folded_stacks(profile_file):
    """{стек «a;b;c»: мілісекунди} з усіх потоків (evented-профілі: події O / C з часом)."""
    data = json.load(open(profile_file, encoding="utf-8"))
    frames = [f["name"] for f in data["shared"]["frames"]]
    totals = defaultdict(float)
    for profile in data["profiles"]:
        if profile.get("type") != "evented":
            continue
        stack, last = [], None
        for event in profile["events"]:
            at = event["at"]
            if stack and last is not None and at > last:
                names = [frames[i] for i in stack if not SERVICE.match(frames[i])]
                totals[";".join(names)] += at - last
            last = at
            if event["type"] == "O":
                stack.append(event["frame"])
            elif stack:
                stack.pop()
    return totals


def build_tree(stacks):
    root = {"name": "all", "value": 0.0, "children": {}}
    for stack, value in stacks.items():
        node = root
        root["value"] += value
        for name in stack.split(";"):
            node = node["children"].setdefault(name, {"name": name, "value": 0.0, "children": {}})
            node["value"] += value
    return root


def colour(name):
    # Сімейства кольорів за простором імен, щоб на око відрізняти БД, EF, ASP.NET і решту.
    if "Npgsql" in name:
        return "#e7a14b"
    if "EntityFrameworkCore" in name or "Linq" in name:
        return "#d67a5c"
    if "AspNetCore" in name or "Kestrel" in name or "Http" in name:
        return "#7aa7d6"
    if "PollingPlatform" in name:
        return "#6cbf6a"
    if "Json" in name:
        return "#b48ad6"
    return "#c9c38a"


def render(root, title, width=1600, row=17):
    rows = []

    def walk(node, x, depth):
        w = node["value"] / root["value"] * width if root["value"] else 0
        if w < 0.5:
            return 0
        rows.append((x, depth, w, node))
        cx = x
        for child in sorted(node["children"].values(), key=lambda c: c["name"]):
            cx += walk(child, cx, depth + 1)
        return w

    walk(root, 0, 0)
    depth_max = max(d for _, d, _, _ in rows) + 1
    height = depth_max * row + 40
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" font-family="monospace" font-size="11">',
           f'<rect width="100%" height="100%" fill="#fdfdf6"/><text x="6" y="16" font-size="13">{html.escape(title)}</text>']
    for x, depth, w, node in rows:
        y = height - (depth + 1) * row
        share = 100 * node["value"] / root["value"]
        label = f'{node["name"]} ({share:.1f}%)'
        out.append(f'<g><title>{html.escape(label)}</title><rect x="{x:.1f}" y="{y}" width="{w:.1f}" height="{row - 1}" '
                   f'fill="{colour(node["name"])}" rx="2"/>')
        chars = int(w / 6.6)
        if chars >= 4:
            text = label if len(label) <= chars else label[: chars - 2] + ".."
            out.append(f'<text x="{x + 3:.1f}" y="{y + row - 5}">{html.escape(text)}</text>')
        out.append("</g>")
    out.append("</svg>")
    return "\n".join(out)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("profile")
    parser.add_argument("svg")
    parser.add_argument("--title", default="dotnet-trace thread time")
    parser.add_argument("--all", action="store_true", help="keep UNMANAGED_CODE_TIME too (wall clock)")
    parser.add_argument("--folded", help="also write folded stacks (Brendan Gregg format)")
    args = parser.parse_args()

    stacks = folded_stacks(args.profile)
    total = sum(stacks.values())
    if not args.all:
        stacks = {s: v for s, v in stacks.items() if s.endswith("CPU_TIME")}
    working = sum(stacks.values())
    title = (f"{args.title} — {'all thread time' if args.all else 'CPU_TIME only'}: {working / 1000:.1f} s of "
             f"{total / 1000:.1f} s sampled ({100 * working / total:.1f} %)")
    open(args.svg, "w", encoding="utf-8").write(render(build_tree(stacks), title))
    if args.folded:
        with open(args.folded, "w", encoding="utf-8") as f:
            for stack, value in sorted(stacks.items(), key=lambda kv: -kv[1]):
                f.write(f"{stack} {int(value * 1000)}\n")
    print(title)


if __name__ == "__main__":
    main()
