"""Сценарії відмов БД для лаби 6 (пункт 2.5 і третій пункт процедури захисту).

Паралельно зі сценарієм іде потік анонімних читань каталогу: так видно, чи бачив їх відмову користувач.

  1. Втрата Replica: читання без помилок переходять на Primary (Primary Fallback), записи працюють.
  2. Втрата Primary: читання лишаються на Replica, записи і строгі читання одразу отримують 503 Read-Only Mode.
  3. Втрата обох: /health дає 503, балансувальник виключає вузли; після старту все повертається без рестарту backend.
     З лаби 7 (ADR 0057) зупиняються обидва вузли Shard A, а Shard B живий: /health лишається 200 (Degraded), каталог
     віддає опитування Shard B із заголовком X-Shard-Unavailable: A, а опитування Shard A — одразу 503. З SHARD_COUNT=1
     поведінка та сама, що в лабі 6.

Скрипт сам зупиняє вузли (`docker compose stop`) і завжди запускає їх знову (`finally`).
Запуск з кореня репозиторію (стек піднятий):  python scripts/db-failure-check.py [--pause]
  --pause  чекати Enter перед кожним кроком — зручно на захисті, щоб пояснювати по ходу.
Лише стандартна бібліотека Python. Вивід англійською — щоб не залежати від кодування консолі.
Код виходу 0 — усі перевірки пройшли.
"""
import argparse
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

from shardlib import backend_config

API = os.environ.get("API", "http://127.0.0.1:8080")
PRIMARY, REPLICA = "postgres", "postgres-replica"
CATALOG = "/api/polls?status=active&pageSize=5"
READERS = 4
FAST_MS = 500  # контрольована відмова має бути миттєвою, а не 13–19 с повторів EF

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


def call(method, path, token=None, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            status, headers = resp.status, resp.headers
    except urllib.error.HTTPError as err:
        raw = err.read()
        status, headers = err.code, err.headers
    took = (time.perf_counter() - started) * 1000
    try:
        parsed = json.loads(raw) if raw else None
    except ValueError:
        parsed = None  # власна сторінка 503 балансувальника
    return status, parsed, headers, took


def compose(*args):
    subprocess.run(["docker", "compose", *args], capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)


def sql(service, query):
    return subprocess.run(["docker", "compose", "exec", "-T", service, "psql", "-U", "polling", "-d", "polling", "-tAc", query],
                          capture_output=True, text=True, encoding="utf-8", errors="replace").stdout.strip()


class ReadStream:
    """Читачі каталогу у фоні: (час від старту, код або помилка, вузол, мс)."""

    def __enter__(self):
        self.samples, self.stop_flag, self.started = [], threading.Event(), time.perf_counter()
        self.threads = [threading.Thread(target=self.run, daemon=True) for _ in range(READERS)]
        for thread in self.threads:
            thread.start()
        return self

    def run(self):
        while not self.stop_flag.is_set():
            at = time.perf_counter() - self.started
            try:
                status, _, headers, took = call("GET", CATALOG)
                self.samples.append((at, status, headers.get("X-DB-Node"), took))
            except OSError as err:
                self.samples.append((at, type(err).__name__, None, 0.0))
            time.sleep(0.02)

    def now(self):
        return time.perf_counter() - self.started

    def __exit__(self, *_):
        self.stop_flag.set()
        for thread in self.threads:
            thread.join(35)

    def report(self, since):
        """Підсумок читань після моменту `since`."""
        window = [s for s in self.samples if s[0] >= since]
        errors = [s for s in window if s[1] != 200]
        slowest = max((s[3] for s in window), default=0)
        by_node = {}
        for sample in window:
            by_node[sample[2]] = by_node.get(sample[2], 0) + 1
        print(f"  reads after the stop: {len(window)}, errors: {len(errors)}, slowest {slowest:.0f} ms, by node: {by_node}")
        return window, errors


def health():
    status, body, _, _ = call("GET", "/health")
    return status, body


def wait_until(predicate, timeout=45):
    started = time.perf_counter()
    while time.perf_counter() - started < timeout:
        if predicate():
            return time.perf_counter() - started
        time.sleep(0.2)
    return None


def login():
    status, body, _, _ = call("POST", "/api/auth/login", body={"email": "user492@example.com", "password": "Password123!"})
    if status != 200:
        raise RuntimeError(f"login returned {status}")
    return body["accessToken"]


def new_poll(token, title):
    return call("POST", "/api/polls", token, {"title": title, "options": ["A", "B"], "endsAt": "2035-01-01T00:00:00Z"})


def healthy_again():
    """Обидва вузли відновлено і репліка знову приймає WAL."""
    return (sql(PRIMARY, "SELECT count(*) FROM pg_stat_replication WHERE state = 'streaming'") == "1"
            and call("GET", CATALOG)[2].get("X-DB-Node") == "replica")


def replica_loss(token):
    step("1. Replica lost: docker compose stop postgres-replica")
    with ReadStream() as stream:
        time.sleep(1)
        stopped_at = stream.now()
        compose("stop", REPLICA)
        print(f"  replica stopped {stream.now() - stopped_at:.1f} s after the command started")
        time.sleep(6)
        window, errors = stream.report(stopped_at)
    check(not errors, "no reader saw an error")
    # З лаби 7 каталог читає й Shard B, у якого репліка жива, тож заголовок — "primary,replica": досить того, що з'явився Primary.
    check(window and "primary" in (window[-1][2] or ""), f"reads went over to the primary (Primary Fallback): X-DB-Node={window and window[-1][2]}")

    status, body, _, took = new_poll(token, "Written while the replica is down")
    check(status == 201, f"writes still work: HTTP {status} in {took:.0f} ms")
    status, body = health()
    print(f"  /health: HTTP {status} {body and body.get('status')} - {body and body.get('detail')}")
    check(status == 200, "the backends stay in the balancer's pool")

    compose("start", REPLICA)
    took = wait_until(healthy_again)
    check(took is not None, f"after start reads are back on the replica in {took or 0:.1f} s, no backend restart")


def primary_loss(token):
    step("2. Primary lost: docker compose stop postgres")
    with ReadStream() as stream:
        time.sleep(1)
        stopped_at = stream.now()
        compose("stop", PRIMARY)
        print(f"  primary stopped {stream.now() - stopped_at:.1f} s after the command started")
        status, _, _, first_ms = new_poll(token, "Must not be written")
        print(f"  first write right after the stop: HTTP {status} in {first_ms:.0f} ms")
        time.sleep(5)

        print("  -- reads for non-critical scenarios")
        status, _, headers, took = call("GET", "/api/polls/2")
        check(status == 200 and headers.get("X-DB-Node") == "replica", f"poll details: HTTP {status} from {headers.get('X-DB-Node')} in {took:.0f} ms")
        status, body, headers, took = call("GET", "/api/polls/3/results")
        check(status == 200, f"results: HTTP {status}, X-Cache={headers.get('X-Cache')}, X-DB-Node={headers.get('X-DB-Node', '-')} in {took:.0f} ms")

        print("  -- writes and strictly consistent reads")
        # Прогрів на обох backend-ах: перша така відмова на інстансі повільніша (до ~470 мс), і поріг FAST_MS спрацьовував би
        # не через систему, а через холодний шлях коду.
        for _ in range(4):
            new_poll(token, "Must not be written")
        for label, (status, body, _, took) in (
            ("create poll", new_poll(token, "Must not be written")),
            ("vote", call("POST", "/api/polls/1/vote", token, {"optionId": 1})),
            ("login", call("POST", "/api/auth/login", body={"email": "user492@example.com", "password": "Password123!"})),
            ("/me", call("GET", "/api/auth/me", token)),
        ):
            title = body.get("title") if body else None
            check(status == 503 and title == "Read-Only Mode" and took < FAST_MS, f"{label}: HTTP {status} '{title}' in {took:.0f} ms")

        status, body = health()
        print(f"  /health: HTTP {status} {body and body.get('status')} - {body and body.get('detail')}")
        check(status == 200, "the backends stay in the balancer's pool")
        window, errors = stream.report(stopped_at)
    check(not errors, "no catalog reader saw an error")
    check(window and window[-1][2] == "replica", "catalog reads stay on the replica")

    compose("start", PRIMARY)
    took = wait_until(lambda: new_poll(token, "Written after the primary came back")[0] == 201)
    check(took is not None, f"writes work again in {took or 0:.1f} s, no backend restart")
    took = wait_until(healthy_again)
    check(took is not None, f"the replica streams WAL again in {took or 0:.1f} s")


def both_lost():
    if backend_config()["count"] == 1:
        step("3. Both nodes lost")
        compose("stop", REPLICA, PRIMARY)
        took = wait_until(lambda: health()[0] == 503)
        status, body, _, _ = call("GET", CATALOG)
        print(f"  catalog: HTTP {status} ({'the API' if body else 'the balancer'})")
        check(took is not None and status == 503, f"/health reports 503 after {took or 0:.1f} s, clients get a controlled 503")
    else:
        step("3. Both nodes of shard A lost, shard B alive")
        compose("stop", REPLICA, PRIMARY)
        # Кожен backend має власний монітор: чекаємо, поки відмову побачать обидва (HAProxy чергує їх по колу).
        took = wait_until(lambda: all("Shard A: no database node" in ((health()[1] or {}).get("detail") or "") for _ in range(4)))
        status, body = health()
        check(took is not None and status == 200,
              f"/health {status} {body and body.get('status')} after {took or 0:.1f} s: backends stay in the pool for shard B")
        status, body, headers, took_ms = call("GET", CATALOG)
        check(status == 200 and headers.get("X-Shard-Unavailable") == "A",
              f"catalog -> HTTP {status} in {took_ms:.0f} ms, X-Shard-Unavailable={headers.get('X-Shard-Unavailable')}")
        status, body, _, took_ms = call("GET", "/api/polls/1")
        check(status == 503 and took_ms < FAST_MS,
              f"poll #1 (shard A) -> HTTP {status} {body and body.get('title')} in {took_ms:.0f} ms")
    compose("start", PRIMARY, REPLICA)
    took = wait_until(healthy_again)
    check(took is not None, f"the system is back in {took or 0:.1f} s, no backend restart")


def main():
    global pause
    parser = argparse.ArgumentParser(description="Lab 6: database node failures")
    parser.add_argument("--pause", action="store_true", help="wait for Enter before each step")
    pause = parser.parse_args().pause

    try:
        token = login()
        replica_loss(token)
        primary_loss(token)
        both_lost()
    except (RuntimeError, OSError, subprocess.CalledProcessError) as err:
        check(False, f"aborted: {err!r}")
    finally:
        print("\n=== Restoring ===")
        compose("start", PRIMARY, REPLICA)
        print(f"  back to normal in {wait_until(healthy_again) or 0:.1f} s")

    # Лаба 7: лічильники на Primary обох шардів.
    mismatches = sum(int(sql(db, "SELECT count(*) FROM options o WHERE o.vote_count <> (SELECT count(*) FROM votes v WHERE v.option_id = o.id)"))
                     for db in (PRIMARY, "postgres-shard-b"))
    check(mismatches == 0, f"counter mismatches on both shards' primaries: {mismatches}")

    print(f"\n{'ALL PASSED' if not failures else f'FAILED: {len(failures)}'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
