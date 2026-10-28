"""Генератор навантаження для експериментів лаби 3 (П2-2): RR vs Least Connections, scale-out 1 / 2 / 3.

Закритий цикл: N потоків, кожен шле наступний запит одразу після відповіді на попередній, протягом заданого часу.
Кожен потік тримає власне keep-alive з'єднання (як браузер або мобільний клієнт), щоб міряти сервер, а не
відкриття TCP-з'єднань.

Сценарії (усі — на одному свіжому опитуванні з allowVoteChange=true і чотирма варіантами):
  read   — GET /api/polls/{id}/results (кеш у Redis з TTL 10 с, тож здебільшого влучання в кеш);
  write  — POST /api/polls/{id}/vote з випадковим варіантом: голос або зміна голосу того самого користувача —
           саме тут працюють FOR UPDATE і рядкове блокування options.vote_count (ADR 0014, 0017);
  mixed  — 80 % read, 20 % write.

Вивід: RPS, p50 / p95 / p99 / max, відповіді за кодами (окремо 5xx і обриви з'єднання), розподіл по X-Instance-ID
і латентність кожного інстансу. Після прогону з записом — лічильники по кожному варіанту = рядки в votes.

Генератор працює на тій самій машині, що й стек, і ділить з ним CPU; у Python є GIL. Тому числа порівнюємо між
конфігураціями (алгоритм, кількість інстансів) з однаковими параметрами, а абсолютну продуктивність міряємо k6
у лабі 5.

Запуск з кореня репозиторію (стек піднятий):
  python scripts/load.py --scenario read --threads 32 --duration 20 --runs 3
Адреса — балансувальник; кілька адрес через кому розподіляються по черзі на боці клієнта (до лаби 3 або для
порівняння):  API=http://127.0.0.1:8080,http://127.0.0.1:8082 python scripts/load.py
127.0.0.1, а не localhost — див. kill-test.py. Вивід англійською — щоб не залежати від кодування консолі.
"""
import argparse
import http.client
import json
import math
import os
import random
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

BASES = os.environ.get("API", "http://127.0.0.1:8080").split(",")
PASSWORD = "Password123!"
USERS = range(101, 401)          # 300 сід-користувачів; user001 — автор опитування
READ_SHARE_MIXED = 0.8


class Client:
    """Одне keep-alive з'єднання на потік; після обриву — нове з'єднання на наступному запиті."""

    def __init__(self, base):
        parts = urlsplit(base)
        self.host, self.port = parts.hostname, parts.port or 80
        self.conn = None

    def request(self, method, path, token=None, body=None, timeout=30):
        """Повертає (status | назва помилки, тіло | None, X-Instance-ID | None)."""
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        data = json.dumps(body).encode() if body is not None else None
        try:
            if self.conn is None:
                self.conn = http.client.HTTPConnection(self.host, self.port, timeout=timeout)
            self.conn.request(method, path, body=data, headers=headers)
            resp = self.conn.getresponse()
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None), resp.getheader("X-Instance-ID")
        except (ConnectionError, TimeoutError, OSError, http.client.HTTPException) as err:
            if self.conn is not None:
                self.conn.close()
            self.conn = None
            return type(err).__name__, None, None


def compose(*args):
    return subprocess.run(["docker", "compose", *args], capture_output=True, text=True, check=True).stdout.strip()


def sql(query):
    return compose("exec", "-T", "postgres", "psql", "-U", "polling", "-d", "polling", "-tAc", query)


def login(number):
    status, body, _ = Client(BASES[0]).request(
        "POST", "/api/auth/login", body={"email": f"user{number:03d}@example.com", "password": PASSWORD})
    if status != 200:
        sys.exit(f"login failed for user{number:03d}: {status}")
    return body["accessToken"]


def new_poll(author):
    client = Client(BASES[0])
    status, poll, _ = client.request("POST", "/api/polls", author, {
        "title": f"Load test {int(time.time() * 1000)}", "options": ["A", "B", "C", "D"],
        "endsAt": "2030-01-01T00:00:00Z", "allowVoteChange": True})
    if status != 201:
        sys.exit(f"could not create the poll: {status}")
    status, poll, _ = client.request("PATCH", f"/api/polls/{poll['id']}/publish", author)
    if status != 200:
        sys.exit(f"could not publish the poll: {status}")
    return poll["id"], [o["id"] for o in poll["options"]]


def percentile(sorted_values, p):
    """Найближчий ранг: значення, не менше за яке p % вибірки."""
    if not sorted_values:
        return 0.0
    index = max(0, math.ceil(p / 100 * len(sorted_values)) - 1)
    return sorted_values[index]


def run_once(args, poll_id, options, tokens):
    samples = []                 # (kind, status | error, instance, latency ms)
    lock = threading.Lock()
    deadline = time.monotonic() + args.duration

    def worker(n):
        client = Client(BASES[n % len(BASES)])
        rnd = random.Random(n)
        token = tokens[n % len(tokens)]
        local = []
        while time.monotonic() < deadline:
            if args.scenario == "read" or (args.scenario == "mixed" and rnd.random() < READ_SHARE_MIXED):
                kind, request = "read", ("GET", f"/api/polls/{poll_id}/results", None, None)
            else:
                # Кожен запит запису — від іншого користувача, щоб не мірятися лише з власним блокуванням рядка голосу.
                token = tokens[rnd.randrange(len(tokens))]
                kind, request = "write", ("POST", f"/api/polls/{poll_id}/vote", token, {"optionId": rnd.choice(options)})
            started = time.perf_counter()
            status, _, instance = client.request(*request)
            local.append((kind, status, instance, (time.perf_counter() - started) * 1000))
        with lock:
            samples.extend(local)

    started = time.monotonic()
    with ThreadPoolExecutor(args.threads) as pool:
        list(pool.map(worker, range(args.threads)))
    elapsed = time.monotonic() - started
    return samples, elapsed


def report(samples, elapsed):
    latencies = sorted(s[3] for s in samples)
    codes = {}
    for s in samples:
        codes[s[1]] = codes.get(s[1], 0) + 1
    server_errors = sum(n for c, n in codes.items() if isinstance(c, int) and c >= 500)
    broken = sum(n for c, n in codes.items() if not isinstance(c, int))
    rps = len(samples) / elapsed
    p50, p95, p99 = (percentile(latencies, p) for p in (50, 95, 99))
    print(f"  requests {len(samples)} in {elapsed:.1f}s = {rps:.0f} rps; latency ms p50 {p50:.1f}, p95 {p95:.1f}, "
          f"p99 {p99:.1f}, max {latencies[-1] if latencies else 0:.1f}")
    print(f"  responses {dict(sorted(codes.items(), key=str))}; 5xx {server_errors}, connection errors {broken}")
    by_instance = {}
    for s in samples:
        by_instance.setdefault(s[2] or "-", []).append(s[3])
    for instance, values in sorted(by_instance.items()):
        values.sort()
        print(f"    {instance:<12} {len(values):>7} ({len(values) / len(samples):6.1%})  "
              f"mean {sum(values) / len(values):7.1f} ms  p99 {percentile(values, 99):7.1f} ms")
    return rps, p50, p95, p99, server_errors + broken


def main():
    parser = argparse.ArgumentParser(description="Closed-loop load generator for lab 3 experiments")
    parser.add_argument("--scenario", choices=["read", "write", "mixed"], default="read")
    parser.add_argument("--threads", type=int, default=32)
    parser.add_argument("--duration", type=float, default=20, help="seconds per run")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--no-db-check", action="store_true", help="skip the counter check through docker compose")
    args = parser.parse_args()

    author = login(1)
    with ThreadPoolExecutor(32) as pool:
        tokens = list(pool.map(login, USERS))
    poll_id, options = new_poll(author)
    # Перший голос кожному варіанту — щоб read з першої секунди читав непорожні результати.
    for i, option in enumerate(options):
        Client(BASES[0]).request("POST", f"/api/polls/{poll_id}/vote", tokens[i], {"optionId": option})

    print(f"Scenario {args.scenario}: {args.threads} threads x {args.duration:.0f}s, poll {poll_id}, "
          f"{len(tokens)} users, targets {', '.join(BASES)}")
    summary = []
    for run in range(1, args.runs + 1):
        print(f"\nRun {run}")
        summary.append(report(*run_once(args, poll_id, options, tokens)))

    if args.runs > 1:
        print("\nSummary  run    rps    p50    p95    p99  errors")
        for run, (rps, p50, p95, p99, errors) in enumerate(summary, 1):
            print(f"         {run:>3} {rps:>6.0f} {p50:>6.1f} {p95:>6.1f} {p99:>6.1f} {errors:>7}")
        values = [s[0] for s in summary]
        print(f"  rps spread: min {min(values):.0f}, max {max(values):.0f} "
              f"({(max(values) - min(values)) / max(values):.1%} of max)")

    if args.scenario != "read" and not args.no_db_check:
        mismatches = sql("SELECT count(*) FROM options o WHERE o.vote_count <> "
                         "(SELECT count(*) FROM votes v WHERE v.option_id = o.id)")
        rows = sql(f"SELECT count(*) FROM votes WHERE poll_id = {poll_id}")
        print(f"\nCounters: per-option mismatches in the whole DB = {mismatches}; vote rows in poll {poll_id} = {rows} "
              f"(<= {len(tokens)} users)")
        if mismatches != "0" or int(rows) > len(tokens):
            sys.exit(1)


if __name__ == "__main__":
    main()
