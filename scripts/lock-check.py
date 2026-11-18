"""Distributed lock на читання результатів: власник, що помер, не блокує читачів назавжди (лаба 8, ADR 0061).

Імітуємо інстанс, що взяв lock і впав посеред читання з БД: скрипт збільшує покоління опитування (як голос) і сам
ставить lock цього покоління з чужим токеном і lease бекенду (`SET … NX PX 1000`), який ніхто не звільнить. Потім N
читачів одночасно читають результати через балансувальник. Очікування:
  - усі відповіді 200 і приходять приблизно через lease (lock звільняється сам), а не висять до таймауту клієнта;
  - у БД рівно одне читання агрегату (pg_stat_statements, тег results-load): після спливу lease lock бере один
    запит, решта чекають його запису в кеш;
  - після прогону в Redis не лишилося жодного ключа lock (наш власник звільнив свій, «мертвий» сплив).
Режим бекенду — Lock (за замовчуванням). Код виходу 0 — усе так.

Запуск з кореня репозиторію (стек піднятий):
  python scripts/lock-check.py [--poll 1] [--readers 50]
Лише стандартна бібліотека Python і docker compose. Вивід англійською — щоб не залежати від кодування консолі.
"""
import argparse
import http.client
import json
import os
import socket
import statistics
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

API = urlparse(os.environ.get("API", "http://localhost:8080"))
REDIS = os.environ.get("REDIS", "localhost:6379")
LEASE_MS = 1000  # ResultsDistributedLock.Lease
PRIMARIES = ["postgres", "postgres-shard-b"]


def redis(*args):
    """Одна команда RESP через опублікований порт Redis; повертає рядок відповіді без розбору масивів."""
    host, port = REDIS.split(":")
    payload = f"*{len(args)}\r\n" + "".join(f"${len(str(a).encode())}\r\n{a}\r\n" for a in args)
    with socket.create_connection((host, int(port)), timeout=2) as s:
        s.sendall(payload.encode())
        return s.recv(65536).decode()


def psql(service, sql):
    out = subprocess.run(["docker", "compose", "exec", "-T", service, "psql", "-U", "polling", "-d", "polling",
                          "-tAc", sql], capture_output=True, text=True, check=True)
    return out.stdout.strip()


def db_loads():
    return sum(int(psql(s, "SELECT coalesce(sum(calls), 0) FROM pg_stat_statements "
                           "WHERE query LIKE '%results-load%'") or 0) for s in PRIMARIES)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--poll", type=int, default=1)
    parser.add_argument("--readers", type=int, default=50)
    args = parser.parse_args()

    connections = [http.client.HTTPConnection(API.hostname, API.port or 80, timeout=30) for _ in range(args.readers)]
    for conn in connections:
        conn.request("GET", "/health")
        conn.getresponse().read()

    for s in PRIMARIES:
        psql(s, "SELECT pg_stat_statements_reset()")
    gen = int(redis("INCR", f"polling:results:gen:{args.poll}").strip().lstrip(":"))
    lock_key = f"polling:results:lock:{args.poll}:g{gen}"
    reply = redis("SET", lock_key, "dead-owner", "PX", LEASE_MS, "NX")
    if not reply.startswith("+OK"):
        sys.exit(f"could not plant the dead owner's lock {lock_key}: {reply!r}")
    planted = time.monotonic()
    print(f"poll {args.poll}: generation -> {gen}, planted {lock_key} = dead-owner, PX {LEASE_MS} (never released)")

    barrier = threading.Barrier(args.readers)

    def read(conn):
        barrier.wait()
        start = time.monotonic()
        conn.request("GET", f"/api/polls/{args.poll}/results")
        resp = conn.getresponse()
        body = resp.read()
        return resp.status, time.monotonic() - start, time.monotonic() - planted, \
            json.loads(body).get("generatedAt") if resp.status == 200 else None

    with ThreadPoolExecutor(args.readers) as pool:
        results = list(pool.map(read, connections))

    statuses = [r[0] for r in results]
    latencies = [r[1] * 1000 for r in results]
    since_lock = [r[2] * 1000 for r in results]
    loads = db_loads()
    leftover = redis("KEYS", "polling:results:lock:*")
    left = 0 if leftover.startswith("*0") else int(leftover.split("\r\n")[0].lstrip("*"))

    print(f"  {args.readers} simultaneous readers: statuses {sorted(set(statuses))}, "
          f"latency ms min {min(latencies):.0f} / median {statistics.median(latencies):.0f} / max {max(latencies):.0f}, "
          f"answered {min(since_lock):.0f}-{max(since_lock):.0f} ms after the dead lock was planted")
    print(f"  distinct generatedAt: {len({r[3] for r in results})}, DB loads (pg_stat_statements): {loads}, "
          f"lock keys left in Redis: {left}")

    checks = [
        ("all readers got 200", all(s == 200 for s in statuses)),
        ("nobody answered before the lease expired", min(since_lock) >= LEASE_MS * 0.9),
        ("nobody waited much longer than the lease", max(since_lock) <= LEASE_MS + 1000),
        ("exactly one DB load", loads == 1),
        ("no lock keys left", left == 0),
    ]
    for name, ok in checks:
        print(f"  {'OK  ' if ok else 'FAIL'} {name}")
    passed = all(ok for _, ok in checks)
    print("ALL CHECKS PASSED" if passed else "SOME CHECKS FAILED")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
