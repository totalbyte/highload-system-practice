"""Перевірка Read/Write Separation для лаби 6 (пункти 2.2, 2.3).

  1. Класифікація: кожна операція йде на очікуваний вузол (заголовок X-DB-Node).
  2. Незалежний доказ: лічильники транзакцій самого PostgreSQL. Серія читань каталогу має навантажити Replica, а не Primary.

Запуск з кореня репозиторію (стек піднятий):  python scripts/rw-routing-check.py [--pause] [--reads 300]
  --pause  чекати Enter перед кожним кроком — зручно на захисті, щоб пояснювати по ходу.
Опитування №1 (гаряче, зміна голосу дозволена) отримує голос від user499. Лише стандартна бібліотека Python.
Вивід англійською — щоб не залежати від кодування консолі. Код виходу 0 — усі перевірки пройшли.
"""
import argparse
import http.client
import json
import os
import subprocess
import sys
import time
import urllib.parse

API = os.environ.get("API", "http://127.0.0.1:8080")
PRIMARY, REPLICA = "postgres", "postgres-replica"
# Сесія, що простоює, передає свою статистику в pg_stat_database із затримкою до 10 с (виміряно: лічильник росте ще ≈ 10 с
# після останнього запиту). З меншим очікуванням перевірка залежала б від таймінгу.
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
        # Поки чекаємо, HAProxy закриває простояне keep-alive з'єднання (timeout http-request 10s). Після close()
        # http.client сам відкриє нове, а не надішле запит у вже закритий сокет.
        connection.close()


def call(method, path, token=None, body=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    connection.request(method, path, json.dumps(body) if body is not None else None, headers)
    resp = connection.getresponse()
    raw = resp.read()
    return resp.status, json.loads(raw) if raw else None, resp.headers


def expect(label, expected_node, expected_status, method, path, token=None, body=None):
    """Запит і перевірка коду та вузла. expected_node None — запит не мав торкатися БД."""
    status, data, headers = call(method, path, token, body)
    node = headers.get("X-DB-Node")
    ok = status in expected_status and node == expected_node
    check(ok, f"{label:<34} HTTP {status}  X-DB-Node={node or '-':<8} X-Cache={headers.get('X-Cache', '-')}")
    return data


def transactions(service):
    done = subprocess.run(
        ["docker", "compose", "exec", "-T", service, "psql", "-U", "polling", "-d", "polling", "-tAc",
         "SELECT xact_commit + xact_rollback FROM pg_stat_database WHERE datname = current_database()"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)
    return int(done.stdout.strip())


def classification():
    step("1. Every operation goes to the node its classification requires")
    print("  -- eventual consistency: replica")
    expect("GET catalog", "replica", {200}, "GET", "/api/polls?status=active&pageSize=5")
    hot = expect("GET poll details", "replica", {200}, "GET", "/api/polls/1")

    print("  -- strict consistency: primary")
    login = {"email": "user499@example.com", "password": "Password123!"}
    token = expect("POST login (authentication)", "primary", {200}, "POST", "/api/auth/login", body=login)["accessToken"]
    expect("GET /me", "primary", {200}, "GET", "/api/auth/me", token)

    print("  -- writes and the reads that decide them: primary")
    created = expect("POST poll", "primary", {201}, "POST", "/api/polls", token, {
        "title": "Routing check", "options": ["A", "B"], "endsAt": "2035-01-01T00:00:00Z"})
    fresh = created["id"]
    expect("PATCH publish", "primary", {200}, "PATCH", f"/api/polls/{fresh}/publish", token)
    option = hot["options"][0]["id"]
    expect("POST vote", "primary", {200, 201}, "POST", "/api/polls/1/vote", token, {"optionId": option})
    expect("GET my vote", "primary", {200}, "GET", "/api/polls/1/vote", token)

    print("  -- results: a miss is read from the primary, a hit touches no database")
    expect("GET results (miss)", "primary", {200}, "GET", f"/api/polls/{fresh}/results")
    expect("GET results (hit)", None, {200}, "GET", f"/api/polls/{fresh}/results")


def independent_proof(reads):
    step(f"2. PostgreSQL's own counters during {reads} catalog reads")
    primary_before, replica_before = transactions(PRIMARY), transactions(REPLICA)
    nodes = set()
    for _ in range(reads):
        status, _, headers = call("GET", "/api/polls?status=active&pageSize=5")
        nodes.add((status, headers.get("X-DB-Node")))
    print(f"  waiting {STATS_FLUSH_S} s for PostgreSQL to publish the statistics...")
    time.sleep(STATS_FLUSH_S)
    primary_delta = transactions(PRIMARY) - primary_before
    replica_delta = transactions(REPLICA) - replica_before
    print(f"  transactions: primary +{primary_delta}, replica +{replica_delta}")
    print("  (the primary's number is background: health checks and these measurements)")
    check(nodes == {(200, "replica")}, f"every read answered by the replica: {sorted(nodes, key=str)}")
    # Одне читання каталогу дає кілька транзакцій (виміряно ≈ 4), тож менше ніж reads означало б, що читання йшли не сюди.
    check(replica_delta >= reads, "the replica executed the catalog reads")
    # Порівняння з реплікою, а не з reads: фон Primary не залежить від кількості читань і при малому --reads перевищив би поріг.
    check(primary_delta < replica_delta / 2, "the primary did not execute them")


def main():
    global pause
    parser = argparse.ArgumentParser(description="Lab 6: check read/write routing")
    parser.add_argument("--pause", action="store_true", help="wait for Enter before each step")
    parser.add_argument("--reads", type=int, default=300, help="catalog reads in the counter check")
    args = parser.parse_args()
    pause = args.pause

    try:
        classification()
        independent_proof(args.reads)
    except (OSError, TypeError, KeyError, http.client.HTTPException, subprocess.CalledProcessError) as err:
        check(False, f"aborted: {err!r}")

    print(f"\n{'ALL PASSED' if not failures else f'FAILED: {len(failures)}'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
