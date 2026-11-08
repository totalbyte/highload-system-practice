"""Демонстрація Stale Read і Read-After-Write для лаби 6 (пункти 2.3, 2.4 і другий пункт процедури захисту).

На репліці вмикається керована затримка відтворення WAL (recovery_min_apply_delay), бо власна затримка на одній машині
становить мілісекунди. Далі автор створює і публікує опитування, а скрипт одразу читає його з різних боків:

  1. Захист увімкнено: сторонній читач отримує 404 (Stale Read), автор бачить опитування з Primary.
     Позначка в Redis спільна для інстансів, а після TTL автор знову читає з репліки.
  2. Захист вимкнено (STICKY_TTL_SECONDS=0, backend-и перестворюються): автор сам отримує 404 на щойно створене.
  3. Межа механізму: затримка більша за TTL, і автор після завершення TTL теж бачить застарілі дані.

Запуск з кореня репозиторію (стек піднятий):  python scripts/stale-read-demo.py [--pause] [--lag 3]
  --pause  чекати Enter перед кожним кроком — зручно на захисті, щоб пояснювати по ходу.
Затримку і backend-и скрипт завжди повертає у вихідний стан (`finally`). Лише стандартна бібліотека Python.
Вивід англійською — щоб не залежати від кодування консолі. Код виходу 0 — усі перевірки пройшли.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

API = os.environ.get("API", "http://127.0.0.1:8080")
STICKY_TTL_S = int(os.environ.get("STICKY_TTL_SECONDS", "5"))
PASSWORD = "Password123!"

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
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else None, resp.headers
    except urllib.error.HTTPError as err:
        # Тіло помилки не читаємо як JSON: поки backend-и перестворюються, HAProxy відповідає власною 503 у форматі HTML.
        err.read()
        return err.code, None, err.headers


def compose(*args, env=None):
    return subprocess.run(["docker", "compose", *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", check=True, env={**os.environ, **(env or {})}).stdout.strip()


def replica_sql(query):
    return compose("exec", "-T", "postgres-replica", "psql", "-U", "polling", "-d", "polling", "-tAc", query)


def set_lag(seconds):
    if seconds:
        replica_sql(f"ALTER SYSTEM SET recovery_min_apply_delay = '{seconds}s'")
    else:
        replica_sql("ALTER SYSTEM RESET recovery_min_apply_delay")
    replica_sql("SELECT pg_reload_conf()")
    print(f"  replica: recovery_min_apply_delay = {replica_sql('SHOW recovery_min_apply_delay')}")


def set_sticky_ttl(seconds):
    """Перестворює backend-и з новим TTL і чекає, поки балансувальник знову бачить обидва."""
    print(f"  recreating the backends with STICKY_TTL_SECONDS={seconds}...")
    compose("up", "-d", "backend-1", "backend-2", env={"STICKY_TTL_SECONDS": str(seconds)})
    for _ in range(60):
        seen = set()
        for _ in range(6):
            try:
                status, _, headers = call("GET", "/health")
                if status == 200:
                    seen.add(headers.get("X-Instance-ID"))
            except OSError:
                pass
        if len(seen) == 2:
            return
        time.sleep(1)
    raise RuntimeError("the backends did not come back")


def login(email):
    return call("POST", "/api/auth/login", body={"email": email, "password": PASSWORD})[1]["accessToken"]


def publish_poll(token, title):
    status, poll, _ = call("POST", "/api/polls", token, {"title": title, "options": ["A", "B"], "endsAt": "2035-01-01T00:00:00Z"})
    if status != 201:
        raise RuntimeError(f"create poll returned {status}")
    status, _, _ = call("PATCH", f"/api/polls/{poll['id']}/publish", token)
    if status != 200:
        raise RuntimeError(f"publish returned {status}")
    return poll["id"]


def read(label, poll_id, token=None):
    status, _, headers = call("GET", f"/api/polls/{poll_id}", token)
    node, instance = headers.get("X-DB-Node", "-"), headers.get("X-Instance-ID", "?")
    print(f"  {label:<36} HTTP {status}  X-DB-Node={node:<8} {instance}")
    return status, node, instance


def wait_visible(poll_id):
    """Секунди, поки сторонній читач не побачить опитування: це і є видима затримка реплікації."""
    started = time.perf_counter()
    while time.perf_counter() - started < 30:
        if call("GET", f"/api/polls/{poll_id}")[0] == 200:
            return time.perf_counter() - started
        time.sleep(0.1)
    return None


def protected(author, lag):
    step(f"1. Replication lag {lag} s, sticky routing ON (TTL {STICKY_TTL_S} s)")
    set_lag(lag)
    poll_id = publish_poll(author, f"Stale read demo {int(time.time())}")
    print(f"  the author created and published poll {poll_id}; reading at once:")

    status, node, _ = read("anonymous reader", poll_id)
    check(status == 404 and node == "replica", "STALE READ: the replica does not have the poll yet")

    instances = set()
    for attempt in (1, 2):
        status, node, instance = read(f"author, read {attempt}", poll_id, author)
        instances.add(instance)
        check(status == 200 and node == "primary", "the author sees their own write, read from the primary")
    print(f"  author's reads were served by: {sorted(instances)} (the mark lives in Redis, not in one instance)")

    took = wait_visible(poll_id)
    print(f"  the anonymous reader saw the poll after {took:.1f} s" if took else "  the poll never became visible")
    check(took is not None and took >= lag - 1, "the poll reached the replica only after the lag")

    time.sleep(STICKY_TTL_S + 1)
    status, node, _ = read(f"author, {STICKY_TTL_S + 1} s after the write", poll_id, author)
    check(status == 200 and node == "replica", "after the TTL the author reads from the replica again")


def unprotected(author, lag):
    step(f"2. Replication lag {lag} s, sticky routing OFF")
    set_sticky_ttl(0)
    poll_id = publish_poll(author, f"No protection {int(time.time())}")
    print(f"  the author created and published poll {poll_id}; reading at once:")
    status, node, _ = read("author", poll_id, author)
    check(status == 404 and node == "replica", "without protection the author gets 404 for their own poll")
    set_sticky_ttl(STICKY_TTL_S)


def limit(author):
    lag = STICKY_TTL_S + 3
    step(f"3. The limit of the mechanism: lag {lag} s is longer than TTL {STICKY_TTL_S} s")
    set_lag(lag)
    poll_id = publish_poll(author, f"Lag over TTL {int(time.time())}")
    status, node, _ = read("author, at once", poll_id, author)
    check(status == 200 and node == "primary", "inside the TTL the author is protected")
    time.sleep(STICKY_TTL_S + 1)
    status, node, _ = read(f"author, {STICKY_TTL_S + 1} s later", poll_id, author)
    check(status == 404 and node == "replica", "after the TTL the replica is still behind: the TTL must exceed the lag")


def main():
    global pause
    parser = argparse.ArgumentParser(description="Lab 6: stale read and read-after-write demo")
    parser.add_argument("--pause", action="store_true", help="wait for Enter before each step")
    parser.add_argument("--lag", type=int, default=3, help="artificial replication lag, seconds")
    args = parser.parse_args()
    pause = args.pause

    try:
        author = login("user497@example.com")
        protected(author, args.lag)
        unprotected(author, args.lag)
        limit(author)
    except (RuntimeError, OSError, subprocess.CalledProcessError) as err:
        check(False, f"aborted: {err!r}")
    finally:
        print("\n=== Restoring ===")
        set_lag(0)
        set_sticky_ttl(STICKY_TTL_S)

    print(f"\n{'ALL PASSED' if not failures else f'FAILED: {len(failures)}'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
