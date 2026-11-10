"""Перевірка Shard Router для лаби 7 (пункт 2.2, демонстрація 2 на захисті).

  1. Нові опитування потрапляють на шард, який обчислює роутер за id, і лише туди (перевірка прямо в БД обох шардів).
  2. Детермінованість: повторні запити через різні інстанси backend ідуть на той самий шард.
  3. Операції з одним опитуванням (публікація, голос, результати) — shard-local, каталог — на всіх шардах (fan-out).
  4. Сід розкладено правильно: кожне опитування лежить на своєму шарді, users — лише на Shard A.

Запуск з кореня репозиторію (стек піднятий):  python scripts/shard-routing-check.py [--pause] [--polls 10]
Лише стандартна бібліотека Python. Вивід англійською — щоб не залежати від кодування консолі. Код виходу 0 — усе пройшло.
"""
import argparse
import http.client
import json
import os
import subprocess
import sys
import urllib.parse

from shardlib import backend_config, name, psql, shard_for

API = os.environ.get("API", "http://127.0.0.1:8080")

url = urllib.parse.urlsplit(API)
connection = http.client.HTTPConnection(url.hostname, url.port, timeout=30)
failures = []
pause = False
config = {}


def check(ok, label):
    print(f"  [{'OK' if ok else 'FAIL'}] {label}")
    if not ok:
        failures.append(label)


def step(title):
    print(f"\n=== {title} ===")
    if pause:
        input("  (Enter to continue) ")
        # Поки чекаємо, HAProxy закриває простояне keep-alive з'єднання; після close() http.client відкриє нове.
        connection.close()


def call(method, path, token=None, body=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    connection.request(method, path, json.dumps(body) if body is not None else None, headers)
    resp = connection.getresponse()
    raw = resp.read()
    return resp.status, json.loads(raw) if raw else None, resp.headers


def expected(poll_id):
    return name(shard_for(poll_id, **config))


def where_is(poll_id):
    """Шарди, на яких справді лежить рядок опитування."""
    shards = []
    for shard in ["A", "B"][:config["count"]]:
        if psql(shard, f"SELECT count(*) FROM polls WHERE id = {poll_id}") == "1":
            shards.append(shard)
    return shards


def new_polls(token, count):
    step(f"1. {count} new polls: each one lands on the shard the router computes, and only there")
    created = []
    for i in range(count):
        status, data, headers = call("POST", "/api/polls", token, {
            "title": f"Shard routing check {i + 1}", "options": ["Yes", "No"], "endsAt": "2035-01-01T00:00:00Z"})
        if status != 201:
            check(False, f"POST poll -> HTTP {status}")
            continue
        poll_id = data["id"]
        want = expected(poll_id)
        stored = where_is(poll_id)
        # Створення завжди торкається й Shard A: там глобальна послідовність poll_ids та ім'я автора в users (ADR 0054).
        touched = ",".join(sorted({"A", want}))
        check(headers.get("X-Shard") == touched and stored == [want],
              f"poll {poll_id:>4}: expected shard {want}, stored on {stored}, X-Shard={headers.get('X-Shard')} (A = id sequence)")
        created.append(poll_id)
    per_shard = {s: sum(1 for p in created if expected(p) == s) for s in ["A", "B"]}
    print(f"  new polls per shard: {per_shard}")
    return created


def determinism(token, polls):
    step("2. The same poll always goes to the same shard, whichever backend instance answers")
    for poll_id in polls[:3]:
        seen = set()
        instances = set()
        for _ in range(6):
            status, _, headers = call("GET", f"/api/polls/{poll_id}", token)
            seen.add((status, headers.get("X-Shard")))
            instances.add(headers.get("X-Instance-ID"))
        check(seen == {(200, expected(poll_id))},
              f"poll {poll_id:>4}: 6 reads -> {sorted(seen, key=str)} via {sorted(i or '-' for i in instances)}")


def shard_local_and_fan_out(token, polls):
    step("3. Operations on one poll touch one shard; the catalog touches every shard")
    by_shard = {}
    for poll_id in polls:
        by_shard.setdefault(expected(poll_id), poll_id)
    for shard, poll_id in sorted(by_shard.items()):
        status, data, headers = call("PATCH", f"/api/polls/{poll_id}/publish", token)
        check(status == 200 and headers.get("X-Shard") == shard, f"publish poll {poll_id} -> HTTP {status}, X-Shard={headers.get('X-Shard')}")
        option = data["options"][0]["id"] if data else 0
        status, _, headers = call("POST", f"/api/polls/{poll_id}/vote", token, {"optionId": option})
        check(status == 201 and headers.get("X-Shard") == shard, f"vote in poll {poll_id} -> HTTP {status}, X-Shard={headers.get('X-Shard')}")
        votes = {s: psql(s, f"SELECT count(*) FROM votes WHERE poll_id = {poll_id}") for s in ["A", "B"][:config["count"]]}
        check(votes.get(shard) == "1" and all(v == "0" for s, v in votes.items() if s != shard),
              f"the vote row is only on shard {shard}: {votes}")
        status, _, headers = call("GET", f"/api/polls/{poll_id}/results")
        check(status == 200 and headers.get("X-Shard") == shard,
              f"results of poll {poll_id} -> HTTP {status}, X-Shard={headers.get('X-Shard')}, X-Cache={headers.get('X-Cache')}")
    all_shards = ",".join(["A", "B"][:config["count"]])
    status, data, headers = call("GET", "/api/polls?pageSize=20")
    check(status == 200 and headers.get("X-Shard") == all_shards,
          f"catalog -> HTTP {status}, X-Shard={headers.get('X-Shard')}, totalCount={data and data['totalCount']}")
    status, _, headers = call("GET", "/api/auth/me", token)
    check(status == 200 and headers.get("X-Shard") == "A", f"/me (users) -> HTTP {status}, X-Shard={headers.get('X-Shard')}")


def placement():
    step("4. Every poll in the database sits on its own shard; users only on shard A")
    total = 0
    for shard in ["A", "B"][:config["count"]]:
        ids = [int(x) for x in psql(shard, "SELECT id FROM polls ORDER BY id").split()]
        wrong = [i for i in ids if expected(i) != shard]
        total += len(ids)
        check(not wrong, f"shard {shard}: {len(ids)} polls, misplaced: {wrong[:10] or 'none'}")
    if config["count"] > 1:
        check(psql("B", "SELECT count(*) FROM users") == "0", "shard B has no users (the table is global, on shard A)")
    print(f"  polls on all shards: {total}")


def cleanup(token, polls):
    # Невикористані чернетки прибираємо, щоб повторні запуски не засмічували каталог.
    for poll_id in polls:
        call("DELETE", f"/api/polls/{poll_id}", token)


def main():
    global pause, config
    parser = argparse.ArgumentParser(description="Lab 7: check the shard router")
    parser.add_argument("--pause", action="store_true", help="wait for Enter before each step")
    parser.add_argument("--polls", type=int, default=10, help="how many new polls to create")
    args = parser.parse_args()
    pause = args.pause

    try:
        config = backend_config()
        print(f"backend-1 sharding: {config}")
        status, data, _ = call("POST", "/api/auth/login", body={"email": "user002@example.com", "password": "Password123!"})
        token = data["accessToken"]
        polls = new_polls(token, args.polls)
        determinism(token, polls)
        shard_local_and_fan_out(token, polls)
        placement()
        cleanup(token, polls)
    except (OSError, TypeError, KeyError, http.client.HTTPException, subprocess.CalledProcessError) as err:
        check(False, f"aborted: {err!r}")

    print(f"\n{'ALL PASSED' if not failures else f'FAILED: {len(failures)}'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
