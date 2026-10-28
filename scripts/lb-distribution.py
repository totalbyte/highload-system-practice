"""Розподіл запитів по інстансах через балансувальник (лаба 3, П1-4, пункти 2.3.1–2.3.2 методички).

Шле N послідовних GET через балансувальник і рахує, який інстанс відповів (заголовок X-Instance-ID). Поруч — ті самі
числа зі сторінки статистики HAProxy (приріст відповідей кожного сервера за час прогону), щоб на захисті було видно:
скрипт і балансувальник рахують однаково. Алгоритм і ваги читаються з haproxy/haproxy.cfg — перемикання:
`bash scripts/lb-algorithm.sh ...`.

Запуск з кореня репозиторію (стек піднятий):
  python scripts/lb-distribution.py                 # 300 запитів на /health
  python scripts/lb-distribution.py -n 600 --path "/api/polls?pageSize=5"
Одне keep-alive з'єднання на весь прогін: балансувальник у режимі http розподіляє кожен запит окремо, а не з'єднання.
127.0.0.1, а не localhost — на Windows відмова з'єднання з localhost займає ~4 с (спершу IPv6). Стандартна бібліотека.
"""
import argparse
import collections
import csv
import http.client
import io
import os
import re
import urllib.request

LB = os.environ.get("LB", "127.0.0.1:8080")
STATS = os.environ.get("LB_STATS", "http://127.0.0.1:8404/stats;csv")
CFG = os.path.join(os.path.dirname(__file__), "..", "haproxy", "haproxy.cfg")


def server_responses():
    """Відповіді кожного сервера be_api зі сторінки статистики: {backend-N: (кількість, стан)}."""
    with urllib.request.urlopen(STATS, timeout=5) as r:
        text = r.read().decode().lstrip("# ")
    result = {}
    for row in csv.DictReader(io.StringIO(text)):
        if row["pxname"] == "be_api" and row["svname"].startswith("backend-"):
            total = sum(int(row[k] or 0) for k in ("hrsp_1xx", "hrsp_2xx", "hrsp_3xx", "hrsp_4xx", "hrsp_5xx", "hrsp_other"))
            result[row["svname"]] = (total, row["status"])
    return result


def algorithm():
    with open(CFG, encoding="utf-8") as f:
        cfg = f.read()
    balance = re.search(r"^    balance (\S+)", cfg, re.M).group(1)
    weights = dict(re.findall(r"^    server (backend-\d+) \S+ weight (\d+)", cfg, re.M))
    return balance, weights


def main():
    parser = argparse.ArgumentParser(description="Request distribution through the load balancer")
    parser.add_argument("-n", "--requests", type=int, default=300)
    parser.add_argument("--path", default="/health")
    args = parser.parse_args()

    balance, weights = algorithm()
    before = server_responses()
    seen, codes = collections.Counter(), collections.Counter()
    conn = http.client.HTTPConnection(LB, timeout=30)
    for _ in range(args.requests):
        conn.request("GET", args.path)
        response = conn.getresponse()
        response.read()
        seen[response.getheader("X-Instance-ID") or "?"] += 1
        codes[response.status] += 1
    conn.close()
    after = server_responses()

    print(f"balance {balance}, weights {', '.join(f'{k}={v}' for k, v in sorted(weights.items()))}; "
          f"{args.requests} x GET {args.path}; codes {dict(codes)}")
    print(f"{'instance':<11}{'requests':>9}{'share':>8}   {'HAProxy stats':>13}  state")
    for name in sorted(set(seen) | set(after)):
        if name == "?" or name in after and after[name][1].startswith("MAINT") and not seen[name]:
            continue  # backend-3 без профілю scale: його немає в пулі, і рядок нічого не додає
        stats = after.get(name, (0, "-"))
        delta = stats[0] - before.get(name, (0, ""))[0]
        print(f"{name:<11}{seen[name]:>9}{seen[name] / args.requests:>8.1%}   {delta:>13}  {stats[1]}")


if __name__ == "__main__":
    main()
