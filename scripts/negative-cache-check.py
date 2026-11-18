"""Negative Caching результатів: неіснуюче опитування не б'є в БД, а нове опитування не ховається за ним (лаба 8, ADR 0063).

1. Неіснуючий id (за замовчуванням 9999999): 50 одночасних і ще 100 послідовних читань через балансувальник — усі 404,
   у PostgreSQL рівно одне читання агрегату (pg_stat_statements, тег results-load), у Redis — негативний запис
   `not-found` з TTL ≤ 36 с (30 с ± 20 %).
2. Опитування, якого ще немає: скрипт читає результати наступного id послідовності poll_ids (404 — і негативний запис),
   потім створює опитування (отримує саме цей id) і читає результати як автор — має бути 200, а не 404 з кешу:
   створення збільшує покоління, і негативний запис більше ніхто не читає.
3. Видалення цієї чернетки — знову 404.
Режим бекенду — за замовчуванням (RESULTS_NEGATIVE_CACHING=true). Код виходу 0 — усе так.

Запуск з кореня репозиторію (стек піднятий, ніхто інший не створює опитування в цей момент):
  python scripts/negative-cache-check.py [--missing 9999999]
Лише стандартна бібліотека Python і docker compose. Вивід англійською — щоб не залежати від кодування консолі.
"""
import argparse
import http.client
import json
import os
import socket
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

API = urlparse(os.environ.get("API", "http://localhost:8080"))
REDIS = os.environ.get("REDIS", "localhost:6379")
PRIMARIES = ["postgres", "postgres-shard-b"]


def redis(*args):
    host, port = REDIS.split(":")
    payload = f"*{len(args)}\r\n" + "".join(f"${len(str(a).encode())}\r\n{a}\r\n" for a in args)
    with socket.create_connection((host, int(port)), timeout=2) as s:
        s.sendall(payload.encode())
        return s.recv(65536).decode()


def psql(service, sql):
    return subprocess.run(["docker", "compose", "exec", "-T", service, "psql", "-U", "polling", "-d", "polling",
                           "-tAc", sql], capture_output=True, text=True, check=True).stdout.strip()


def reset_loads():
    for s in PRIMARIES:
        psql(s, "SELECT pg_stat_statements_reset()")


def db_loads():
    return sum(int(psql(s, "SELECT coalesce(sum(calls), 0) FROM pg_stat_statements "
                           "WHERE query LIKE '%results-load%'") or 0) for s in PRIMARIES)


def request(method, path, body=None, token=None):
    conn = http.client.HTTPConnection(API.hostname, API.port or 80, timeout=30)
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    conn.request(method, path, json.dumps(body) if body is not None else None, headers)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp.status, json.loads(data) if data and resp.getheader("Content-Type", "").find("json") >= 0 else None


def value_key(poll_id):
    gen_reply = redis("GET", f"polling:results:gen:{poll_id}")
    gen = 0 if gen_reply.startswith("$-1") else int(gen_reply.split("\r\n")[1])
    return f"polling:results:v1:{poll_id}:g{gen}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--missing", type=int, default=9999999)
    args = parser.parse_args()
    checks = []

    # 1. Неіснуючий id.
    path = f"/api/polls/{args.missing}/results"
    redis("UNLINK", value_key(args.missing))
    reset_loads()
    barrier = threading.Barrier(50)

    def parallel(_):
        barrier.wait()
        return request("GET", path)[0]

    with ThreadPoolExecutor(50) as pool:
        statuses = list(pool.map(parallel, range(50)))
    statuses += [request("GET", path)[0] for _ in range(100)]
    loads = db_loads()
    key = value_key(args.missing)
    value = redis("GET", key)
    ttl = int(redis("PTTL", key).strip().lstrip(":"))
    print(f"1. GET {path}: 150 reads, statuses {sorted(set(statuses))}, DB loads {loads}, "
          f"{key} = {value.split(chr(13) + chr(10))[1] if value.startswith('$') and not value.startswith('$-1') else None}, "
          f"PTTL {ttl} ms")
    checks += [("missing poll: all 404", all(s == 404 for s in statuses)),
               ("missing poll: one DB load for 150 reads", loads == 1),
               ("missing poll: negative entry with TTL <= 36 s", "not-found" in value and 0 < ttl <= 36000)]

    # 2. Опитування, якого ще немає, потім створене.
    status, login = request("POST", "/api/auth/login", {"email": "user001@example.com", "password": "Password123!"})
    if status != 200:
        sys.exit(f"login failed: HTTP {status}")
    token = login["accessToken"]
    last, called = psql("postgres", "SELECT last_value, is_called FROM poll_ids").split("|")
    next_id = int(last) + (1 if called == "t" else 0)
    before = request("GET", f"/api/polls/{next_id}/results", token=token)[0]
    negative_before = "not-found" in redis("GET", value_key(next_id))
    status, created = request("POST", "/api/polls", {"title": "Negative cache check", "options": ["A", "B"],
                                                     "endsAt": "2030-01-01T00:00:00Z"}, token)
    if status != 201:
        sys.exit(f"create poll failed: HTTP {status}")
    after, body = request("GET", f"/api/polls/{created['id']}/results", token=token)
    print(f"2. next id {next_id}: before create {before} (negative entry: {negative_before}), created id {created['id']}, "
          f"author reads results: {after} {body.get('status') if body else ''}")
    checks += [("future poll id: 404 and a negative entry before create", before == 404 and negative_before),
               ("created poll got that id", created["id"] == next_id),
               ("created poll: results 200 at once, not the cached 404", after == 200)]

    # 3. Видалення чернетки.
    deleted = request("DELETE", f"/api/polls/{created['id']}", token=token)[0]
    gone = request("GET", f"/api/polls/{created['id']}/results", token=token)[0]
    print(f"3. delete draft {created['id']}: {deleted}, results afterwards: {gone}")
    checks.append(("deleted draft: results 404", deleted == 204 and gone == 404))

    for name, ok in checks:
        print(f"  {'OK  ' if ok else 'FAIL'} {name}")
    passed = all(ok for _, ok in checks)
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
