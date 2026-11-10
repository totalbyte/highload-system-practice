"""Cross-Shard запити для лаби 7 (пункт 2.4, демонстрація 3 на захисті): ціна fan-out проти shard-local.

  1. Затримка: деталі одного опитування (один шард) проти каталогу (усі шарди), і глибока сторінка каталогу.
  2. Робота БД: скільки транзакцій виконали всі чотири вузли (Primary і Replica обох шардів) на один запит кожного типу —
     за лічильниками самого PostgreSQL.
  3. Втрата цілого шарду: Shard B зупинено повністю — каталог віддає опитування Shard A із заголовком X-Shard-Unavailable,
     опитування Shard A працюють, опитування Shard B — 503. Потім Shard B запускається знову.

Запуск з кореня репозиторію (стек піднятий):  python scripts/cross-shard-check.py [--pause] [--requests 300] [--no-outage]
Лише стандартна бібліотека Python. Вивід англійською — щоб не залежати від кодування консолі. Код виходу 0 — усе пройшло.
"""
import argparse
import http.client
import json
import os
import statistics
import subprocess
import sys
import time
import urllib.parse

from shardlib import backend_config, name, shard_for

API = os.environ.get("API", "http://127.0.0.1:8080")
NODES = ["postgres", "postgres-replica", "postgres-shard-b", "postgres-shard-b-replica"]
SHARD_B = ["postgres-shard-b", "postgres-shard-b-replica"]
# Сесія, що простоює, публікує статистику в pg_stat_database із затримкою до 10 с (виміряно в лабі 6).
STATS_FLUSH_S = 11

url = urllib.parse.urlsplit(API)
connection = http.client.HTTPConnection(url.hostname, url.port, timeout=30)
failures = []
pause = False


def check(ok, label):
    print(f"  [{'OK' if ok else 'FAIL'}] {label}")
    if not ok:
        failures.append(label)


def step(title):
    print(f"\n=== {title} ===")
    if pause:
        input("  (Enter to continue) ")
        connection.close()


def call(method, path, token=None, body=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    started = time.perf_counter()
    try:
        connection.request(method, path, json.dumps(body) if body is not None else None, headers)
        resp = connection.getresponse()
    except (OSError, http.client.HTTPException):
        # HAProxy закриває простояне keep-alive з'єднання — одна повторна спроба з новим.
        connection.close()
        connection.request(method, path, json.dumps(body) if body is not None else None, headers)
        resp = connection.getresponse()
    raw = resp.read()
    took = (time.perf_counter() - started) * 1000
    try:
        data = json.loads(raw) if raw else None
    except ValueError:
        data = None
    return resp.status, data, resp.headers, took


def compose(*args):
    return subprocess.run(["docker", "compose", *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=True).stdout.strip()


def transactions(node):
    return int(compose("exec", "-T", node, "psql", "-U", "polling", "-d", "polling", "-tAc",
                       "SELECT xact_commit + xact_rollback FROM pg_stat_database WHERE datname = current_database()"))


def series(path, count):
    """count запитів підряд: затримки в мс і множина (код, X-Shard)."""
    times, seen = [], set()
    for _ in range(count):
        status, _, headers, took = call("GET", path)
        times.append(took)
        seen.add((status, headers.get("X-Shard")))
    return times, seen


def pick_polls():
    """По одному активному опитуванню з кожного шарду — для shard-local запитів."""
    config = backend_config()
    status, data, _, _ = call("GET", "/api/polls?status=active&pageSize=100")
    by_shard = {}
    for item in data["items"]:
        by_shard.setdefault(name(shard_for(item["id"], **config)), item["id"])
    return config, by_shard


def latency(polls, count):
    step(f"1. Latency: {count} sequential requests of each kind (client side, through HAProxy)")
    kinds = [(f"details, poll {polls['A']} (shard A only)", f"/api/polls/{polls['A']}"),
             (f"details, poll {polls['B']} (shard B only)", f"/api/polls/{polls['B']}"),
             ("catalog page 1 (fan-out to A and B)", "/api/polls?pageSize=20&page=1"),
             ("catalog page 10 (fan-out, deep page)", "/api/polls?pageSize=20&page=10")]
    print(f"  {'request':<40} {'p50 ms':>7} {'p95 ms':>7} {'mean ms':>8}  responses")
    medians = {}
    for label, path in kinds:
        series(path, 20)  # прогрів: пули з'єднань, JIT, кеш планів
        times, seen = series(path, count)
        q = statistics.quantiles(times, n=20)
        medians[label] = statistics.median(times)
        print(f"  {label:<40} {statistics.median(times):7.1f} {q[18]:7.1f} {statistics.mean(times):8.1f}  {sorted(seen, key=str)}")
    local = max(v for k, v in medians.items() if k.startswith("details"))
    fan_out = medians["catalog page 1 (fan-out to A and B)"]
    # Без перевірки: шарди опитуються паралельно, тож на простої каталог чекає лише найповільніший шард і різниця
    # в межах шуму (1.0–1.3x у замірах). Ціну fan-out видно в роботі БД (крок 2) і під навантаженням (етап 6).
    print(f"  fan-out p50 / slowest shard-local p50 = {fan_out / local:.1f}x (parallel fan-out waits for the slowest shard)")


def db_work(polls, count):
    step(f"2. Database work: transactions on all four nodes for {count} requests of each kind")
    print(f"  {'request':<36} " + " ".join(f"{n:>24}" for n in NODES) + "   per request")
    per_request = {}
    # Попередній крок теж читав базу: чекаємо, поки його статистика опублікується, інакше вона потрапить у перший рядок.
    time.sleep(STATS_FLUSH_S)
    for label, path in [("details (one shard)", f"/api/polls/{polls['B']}"),
                        ("catalog page 1 (all shards)", "/api/polls?pageSize=20&page=1")]:
        before = {n: transactions(n) for n in NODES}
        series(path, count)
        time.sleep(STATS_FLUSH_S)
        delta = {n: transactions(n) - before[n] for n in NODES}
        # Фон (health-перевірки монітора, сам psql) — кілька транзакцій на вузол; на count запитів він малий.
        per_request[label] = sum(delta.values()) / count
        touched = [n for n in NODES if delta[n] >= count / 2]
        print(f"  {label:<36} " + " ".join(f"{delta[n]:>24}" for n in NODES) + f"   {per_request[label]:.1f} tx, nodes: {touched}")
    check(per_request["catalog page 1 (all shards)"] > per_request["details (one shard)"],
          "the catalog costs more database transactions than a shard-local read")


def wait_until(predicate, timeout=40):
    started = time.perf_counter()
    while time.perf_counter() - started < timeout:
        if predicate():
            return time.perf_counter() - started
        time.sleep(0.5)
    return None


def outage(polls):
    step("3. Whole shard B lost: docker compose stop postgres-shard-b postgres-shard-b-replica")
    status, data, _, _ = call("POST", "/api/auth/login", body={"email": "user003@example.com", "password": "Password123!"})
    token = data["accessToken"]
    _, full, _, _ = call("GET", "/api/polls?pageSize=100")
    _, poll_a, _, _ = call("GET", f"/api/polls/{polls['A']}")
    try:
        compose("stop", *SHARD_B)
        # Кожен backend має власний монітор: чекаємо, поки відмову побачать обидва (HAProxy чергує їх по колу).
        took = wait_until(lambda: all("Shard B: no database node" in ((call("GET", "/health")[1] or {}).get("detail") or "") for _ in range(4)))
        status, health, _, _ = call("GET", "/health")
        check(status == 200, f"/health {status} {health and health.get('status')} after {took or 0:.1f} s: {health and health.get('detail')}")

        status, data, headers, ms = call("GET", "/api/polls?pageSize=100")
        check(status == 200 and headers.get("X-Shard-Unavailable") == "B",
              f"catalog -> HTTP {status} in {ms:.0f} ms, X-Shard-Unavailable={headers.get('X-Shard-Unavailable')}, "
              f"totalCount {full['totalCount']} -> {data and data['totalCount']}")
        status, _, headers, ms = call("GET", f"/api/polls/{polls['A']}")
        check(status == 200, f"poll {polls['A']} on shard A -> HTTP {status} in {ms:.0f} ms, X-Shard={headers.get('X-Shard')}")
        option = poll_a["options"][0]["id"]
        status, _, _, ms = call("POST", f"/api/polls/{polls['A']}/vote", token, {"optionId": option})
        # 409 — цей користувач уже голосував тут у попередньому запуску: запис однаково дійшов до бази Shard A.
        check(status in (200, 201, 409), f"vote in poll {polls['A']} on shard A -> HTTP {status} in {ms:.0f} ms")
        status, data, _, ms = call("GET", f"/api/polls/{polls['B']}")
        check(status == 503, f"poll {polls['B']} on shard B -> HTTP {status} in {ms:.0f} ms ({data and data.get('title')})")
    finally:
        print("  starting shard B again...")
        compose("start", *SHARD_B)
    took = wait_until(lambda: call("GET", "/api/polls?pageSize=100")[2].get("X-Shard-Unavailable") is None
                      and call("GET", f"/api/polls/{polls['B']}")[0] == 200, timeout=60)
    status, data, headers, _ = call("GET", "/api/polls?pageSize=100")
    check(took is not None and data["totalCount"] == full["totalCount"],
          f"shard B is back in {took or 0:.1f} s, catalog full again (totalCount {data['totalCount']}), no backend restart")


def main():
    global pause
    parser = argparse.ArgumentParser(description="Lab 7: cross-shard queries")
    parser.add_argument("--pause", action="store_true", help="wait for Enter before each step")
    parser.add_argument("--requests", type=int, default=300)
    parser.add_argument("--no-outage", action="store_true", help="skip stopping shard B")
    args = parser.parse_args()
    pause = args.pause

    try:
        config, polls = pick_polls()
        print(f"backend-1 sharding: {config}; shard-local polls: {polls}")
        latency(polls, args.requests)
        db_work(polls, args.requests)
        if not args.no_outage:
            outage(polls)
    except (OSError, TypeError, KeyError, http.client.HTTPException, subprocess.CalledProcessError) as err:
        check(False, f"aborted: {err!r}")

    print(f"\n{'ALL PASSED' if not failures else f'FAILED: {len(failures)}'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
