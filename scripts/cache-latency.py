"""Cold vs hot: час відповіді GET /results при промаху і при попаданні в кеш (лаба 4, П1-6, 2.6.2).

Кожна пара вимірювань:
  - cold — перше читання після інвалідації: скрипт сам збільшує покоління опитування в Redis (`INCR
    polling:results:gen:{id}` через опублікований порт — те саме, що робить голос чи publish, ADR 0041), тож
    backend промахується, читає PostgreSQL і пише в Redis;
  - hot — одразу наступне читання того самого опитування: попадання, без звернення до БД.
Кожне вимірювання перевіряється за X-Cache (MISS / HIT); невідповідні відкидаються. Спершу — прогрів (JIT, пули
з'єднань), його не рахуємо. Запити — через балансувальник по одному keep-alive з'єднанню, по черзі на обидва
інстанси; час — на клієнті, тобто разом із HAProxy і мережею Docker.

Запуск з кореня репозиторію (стек піднятий):
  python scripts/cache-latency.py [--poll 1] [--pairs 500] [--warmup 50]
За замовчуванням — гаряче опитування #1 із сіду. Лише стандартна бібліотека Python.
"""
import argparse
import http.client
import os
import socket
import statistics
import sys
import time
from urllib.parse import urlparse

API = urlparse(os.environ.get("API", "http://localhost:8080"))
REDIS = os.environ.get("REDIS", "localhost:6379")


def redis_incr(key):
    host, port = REDIS.split(":")
    with socket.create_connection((host, int(port)), timeout=2) as s:
        s.sendall(f"*2\r\n$4\r\nINCR\r\n${len(key.encode())}\r\n{key}\r\n".encode())
        reply = s.recv(64).decode()
    if not reply.startswith(":"):
        sys.exit(f"Redis is not reachable on {REDIS}: {reply!r}")


def read(conn, pid):
    started = time.perf_counter()
    conn.request("GET", f"/api/polls/{pid}/results")
    resp = conn.getresponse()
    resp.read()
    took = (time.perf_counter() - started) * 1000
    if resp.status != 200:
        sys.exit(f"GET /api/polls/{pid}/results -> HTTP {resp.status}")
    return resp.getheader("X-Cache"), took


def percentile(values, p):
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, round(p / 100 * len(ordered) + 0.5) - 1))]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--poll", type=int, default=1)
    parser.add_argument("--pairs", type=int, default=500)
    parser.add_argument("--warmup", type=int, default=50)
    args = parser.parse_args()

    conn = http.client.HTTPConnection(API.hostname, API.port or 80, timeout=30)
    gen_key = f"polling:results:gen:{args.poll}"
    cold, hot, discarded = [], [], 0
    for i in range(args.warmup + args.pairs):
        redis_incr(gen_key)
        cold_source, cold_ms = read(conn, args.poll)
        hot_source, hot_ms = read(conn, args.poll)
        if i < args.warmup:
            continue
        if cold_source == "MISS" and hot_source == "HIT":
            cold.append(cold_ms)
            hot.append(hot_ms)
        else:
            discarded += 1

    print(f"GET /api/polls/{args.poll}/results via {API.geturl()}: {len(cold)} pairs "
          f"(+{args.warmup} warm-up, {discarded} discarded: unexpected X-Cache)")
    print(f"  {'':<14}{'p50':>9}{'p95':>9}{'p99':>9}{'mean':>9}{'min':>9}")
    for label, values in (("cold (MISS)", cold), ("hot (HIT)", hot)):
        print(f"  {label:<14}" + "".join(f"{v:8.2f} " for v in (
            percentile(values, 50), percentile(values, 95), percentile(values, 99),
            statistics.mean(values), min(values))) + " ms")
    print(f"  cold / hot, p50: x{percentile(cold, 50) / percentile(hot, 50):.2f}")
    return 0 if cold else 1


if __name__ == "__main__":
    sys.exit(main())
