"""Data Distribution Matrix для лаби 7 (пункт 2.3): як записи й операції запису розкладаються по шардах.

Частина 1 (завжди, без стеку) — модель для всіх стратегій на тих самих id 1..N: частка даних і частка записів на кожен
шард. Записи в моделі — як у реальному сервісі опитувань: голосують переважно в нові опитування (останні 10 % id
отримують 90 % голосів). Так видно головне: Range ділить дані порівну, але всі записи йдуть на один шард.

Частина 2 (--live, стек піднятий) — справжні дані: скрипт генерує набір через API (опитування + голоси), рахує запити
запису по шардах за заголовком X-Shard і незалежно — змінені рядки за лічильниками самого PostgreSQL кожного шарду.

Запуск з кореня репозиторію:  python scripts/shard-distribution.py [--ids 10000] [--live --polls 100 --votes 3000]
Лише стандартна бібліотека Python. Вивід англійською — щоб не залежати від кодування консолі.
"""
import argparse
import http.client
import json
import os
import random
import subprocess
import sys
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

from shardlib import backend_config, name, psql, shard_for

API = os.environ.get("API", "http://127.0.0.1:8080")
STRATEGIES = ["Range", "Modulo", "Hash", "Buckets"]


def percent(part, total):
    return 100.0 * part / total if total else 0.0


def model(ids, range_size, buckets):
    print(f"=== Model: ids 1..{ids}, 2 shards, writes: 90 % of votes go to the newest 10 % of polls ===")
    print(f"(Range boundary = {range_size}: ids below it on shard A, the rest on shard B)\n")
    print("strategy   data A %  data B %   writes A %  writes B %   write imbalance (max / avg)")
    newest = int(ids * 0.9)
    for strategy in STRATEGIES:
        data = [0, 0]
        writes = [0.0, 0.0]
        for poll_id in range(1, ids + 1):
            shard = shard_for(poll_id, strategy, 2, range_size, buckets)
            data[shard] += 1
            # Вага голосів одного опитування: нові (останні 10 %) ділять 90 % голосів, старі — 10 %.
            writes[shard] += 0.9 / (ids - newest) if poll_id > newest else 0.1 / newest
        imbalance = max(writes) / (sum(writes) / 2)
        print(f"{strategy:<9} {percent(data[0], ids):8.1f}  {percent(data[1], ids):8.1f}   "
              f"{percent(writes[0], sum(writes)):10.1f}  {percent(writes[1], sum(writes)):10.1f}   {imbalance:6.2f}")
    print("\nimbalance 1.00 = perfectly even, 2.00 = one shard takes everything.")


class Client:
    """Одне keep-alive з'єднання на потік: http.client не потокобезпечний."""
    local = threading.local()

    @classmethod
    def call(cls, method, path, token=None, body=None):
        if not hasattr(cls.local, "conn"):
            url = urllib.parse.urlsplit(API)
            cls.local.conn = http.client.HTTPConnection(url.hostname, url.port, timeout=30)
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            cls.local.conn.request(method, path, json.dumps(body) if body is not None else None, headers)
            resp = cls.local.conn.getresponse()
        except (OSError, http.client.HTTPException):
            # HAProxy міг закрити простояне з'єднання — одна повторна спроба з новим.
            cls.local.conn.close()
            cls.local.conn.request(method, path, json.dumps(body) if body is not None else None, headers)
            resp = cls.local.conn.getresponse()
        raw = resp.read()
        return resp.status, json.loads(raw) if raw else None, resp.headers


def tuple_writes(shard):
    """Скільки рядків змінив PostgreSQL шарду від старту (вставки + оновлення + видалення)."""
    return int(psql(shard, "SELECT tup_inserted + tup_updated + tup_deleted FROM pg_stat_database "
                           "WHERE datname = current_database()"))


def rows(shard):
    polls, options, votes = psql(shard, "SELECT (SELECT count(*) FROM polls) || ' ' || (SELECT count(*) FROM options) "
                                        "|| ' ' || (SELECT count(*) FROM votes)").split()
    return int(polls), int(options), int(votes)


def live(poll_count, vote_count):
    config = backend_config()
    shards = [name(i) for i in range(config["count"])]
    print(f"\n=== Live dataset on the running stack, backend sharding: {config} ===")

    tokens = []
    for n in range(1, 51):
        status, data, _ = Client.call("POST", "/api/auth/login", body={"email": f"user{n:03d}@example.com", "password": "Password123!"})
        if status != 200:
            sys.exit(f"login user{n:03d}: HTTP {status}")
        tokens.append(data["accessToken"])

    before = {s: tuple_writes(s) for s in shards}
    write_requests = {s: 0 for s in shards}
    lock = threading.Lock()

    def count(headers, poll_id):
        # Шард опитування — з роутера, а X-Shard лише перевіряємо: створення торкається ще й Shard A (послідовність id).
        shard = name(shard_for(poll_id, **config))
        if shard not in (headers.get("X-Shard") or "").split(","):
            print(f"  [FAIL] poll {poll_id}: expected shard {shard}, X-Shard={headers.get('X-Shard')}")
        with lock:
            write_requests[shard] += 1

    def create(i):
        token = tokens[i % len(tokens)]
        status, data, headers = Client.call("POST", "/api/polls", token, {
            "title": f"Distribution {i + 1}", "options": ["A", "B", "C"], "endsAt": "2035-01-01T00:00:00Z", "allowVoteChange": True})
        if status != 201:
            return None
        count(headers, data["id"])
        status, data, headers = Client.call("PATCH", f"/api/polls/{data['id']}/publish", token)
        count(headers, data["id"])
        return data["id"], [o["id"] for o in data["options"]]

    print(f"  creating and publishing {poll_count} polls...")
    with ThreadPoolExecutor(10) as pool:
        polls = [p for p in pool.map(create, range(poll_count)) if p]

    def vote(i):
        poll_id, options = random.choice(polls)
        status, _, headers = Client.call("POST", f"/api/polls/{poll_id}/vote", random.choice(tokens), {"optionId": random.choice(options)})
        if status in (200, 201):
            count(headers, poll_id)
        return status

    print(f"  casting {vote_count} votes from 50 users into random new polls...")
    with ThreadPoolExecutor(20) as pool:
        statuses = list(pool.map(vote, range(vote_count)))
    errors = sum(1 for s in statuses if s not in (200, 201))

    # Сесія PostgreSQL публікує статистику в pg_stat_database із затримкою до 10 с (виміряно в лабі 6, rw-routing-check.py).
    print("  waiting 11 s for PostgreSQL to publish the statistics...")
    time.sleep(11)
    after = {s: tuple_writes(s) for s in shards}
    counts = {s: rows(s) for s in shards}
    total_rows = sum(sum(c) for c in counts.values())
    total_requests = sum(write_requests.values())
    tuples = {s: after[s] - before[s] for s in shards}
    total_tuples = sum(tuples.values())

    print(f"\nData Distribution Matrix (all rows in the database: polls + options + votes; write share of this run)")
    print("shard   polls  options   votes   rows    data %   write requests %   changed rows (PostgreSQL) %")
    for s in shards:
        p, o, v = counts[s]
        print(f"{s:<5} {p:7} {o:8} {v:7} {p + o + v:6}   {percent(p + o + v, total_rows):6.1f}   "
              f"{write_requests[s]:6} = {percent(write_requests[s], total_requests):5.1f}   "
              f"{tuples[s]:8} = {percent(tuples[s], total_tuples):5.1f}")
    codes = sorted({str(c) for c in statuses if c not in (200, 201)})
    # 409 — нормальна відповідь: два потоки випадково віддали перший голос того самого користувача в те саме опитування
    # одночасно, і UNIQUE (poll_id, user_id) пропустив лише один.
    print(f"  vote errors: {errors} of {vote_count} (HTTP {', '.join(codes) or '-'})")
    print("  (changed rows = PostgreSQL tup_inserted + tup_updated + tup_deleted during this run; a vote change updates 3 rows)")


def main():
    parser = argparse.ArgumentParser(description="Lab 7: data distribution matrix")
    parser.add_argument("--ids", type=int, default=10000, help="ids in the model")
    parser.add_argument("--range-size", type=int, default=None, help="Range boundary in the model (default: ids / 2)")
    parser.add_argument("--buckets", type=int, default=64)
    parser.add_argument("--live", action="store_true", help="also generate data on the running stack")
    parser.add_argument("--polls", type=int, default=100)
    parser.add_argument("--votes", type=int, default=3000)
    args = parser.parse_args()

    model(args.ids, args.range_size or args.ids // 2, args.buckets)
    if args.live:
        try:
            live(args.polls, args.votes)
        except (OSError, subprocess.CalledProcessError) as err:
            sys.exit(f"aborted: {err!r}")


if __name__ == "__main__":
    main()
