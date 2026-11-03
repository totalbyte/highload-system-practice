"""Cache Stampede на гарячому опитуванні: скільки запитів у БД дає одна інвалідація (лаба 4, ADR 0044).

Кожен раунд імітує момент одразу після голосу: скрипт збільшує покоління опитування в Redis (`INCR
polling:results:gen:{id}` через опублікований порт — те саме, що робить голос, ADR 0041), і N читачів, відпущені
одночасно бар'єром, читають результати через балансувальник. Без захисту кожен, хто промахнувся до запису в кеш,
сам іде в PostgreSQL. Скільки разів агрегат рахували з БД, видно без жодних логів: кожне читання з БД ставить свій
`generatedAt`, а копія з кешу — той самий. Тож різних `generatedAt` у раунді = звернень до БД.

З single-flight (ADR 0044) промахи одного інстансу чекають один спільний запит у БД, тож звернень у раунді — по
одному на інстанс. Зрідка буває ще одне: читач промахнувся в Redis за мить до того, як політ записав агрегат, а до
таблиці польотів дійшов, коли політ уже завершився, — і почав новий. Код виходу 0, якщо в середньому звернень не
більше 1.5 на інстанс; без захисту їх у кілька разів більше (2026-11-02: 6.7–14.4 на 2 інстанси при 100 читачах).

Запуск з кореня репозиторію (стек піднятий):
  python scripts/cache-stampede-check.py [--poll 1] [--readers 100] [--rounds 20]
Лише стандартна бібліотека Python. Вивід англійською — щоб не залежати від кодування консолі.
"""
import argparse
import http.client
import json
import os
import socket
import statistics
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--poll", type=int, default=1)
    parser.add_argument("--readers", type=int, default=100, help="simultaneous reads right after the invalidation")
    parser.add_argument("--rounds", type=int, default=20)
    args = parser.parse_args()

    # З'єднання відкриті заздалегідь: інакше читачі розтягнулися б на час TCP-з'єднання і перестали б бути одночасними.
    connections = [http.client.HTTPConnection(API.hostname, API.port or 80, timeout=30) for _ in range(args.readers)]
    for conn in connections:
        conn.request("GET", "/health")
        conn.getresponse().read()

    path = f"/api/polls/{args.poll}/results"
    loads, misses, instances = [], [], set()
    with ThreadPoolExecutor(args.readers) as pool:
        for _ in range(args.rounds):
            barrier = threading.Barrier(args.readers)

            def read(conn):
                barrier.wait()
                conn.request("GET", path)
                resp = conn.getresponse()
                body = json.loads(resp.read())
                return resp.getheader("X-Instance-ID"), resp.getheader("X-Cache"), body["generatedAt"]

            redis_incr(f"polling:results:gen:{args.poll}")
            results = list(pool.map(read, connections))
            instances.update(r[0] for r in results)
            loads.append(len({r[2] for r in results}))
            misses.append(sum(r[1] == "MISS" for r in results))

    print(f"GET {path} via {API.geturl()}: {args.rounds} rounds x {args.readers} simultaneous reads "
          f"right after an invalidation, instances: {', '.join(sorted(instances))}")
    print(f"  X-Cache MISS per round:          mean {statistics.mean(misses):6.1f}   max {max(misses)}")
    print(f"  DB loads per round (generatedAt): mean {statistics.mean(loads):6.1f}   max {max(loads)}   "
          f"(per round: {' '.join(map(str, loads))})")
    ok = statistics.mean(loads) <= 1.5 * len(instances)
    print("RESULT:", "about one DB load per instance" if ok else "STAMPEDE: many DB loads per invalidation")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
