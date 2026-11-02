"""Демонстрація кешу результатів для захисту лаби 4 (П1-6): три пункти процедури поспіль.

  1. Hit / Miss: перше читання — MISS (з БД), повторні — HIT (з Redis), на різних інстансах.
  2. Інвалідація: голос → покоління в Redis +1 → наступне читання MISS зі свіжими даними → знову HIT.
     Закриття опитування → MISS зі статусом closed і довгим TTL (ADR 0041).
  3. Fallback: `docker compose stop redis` → читання 200 з X-Cache: BYPASS прямо з БД, голос проходить;
     `start redis` → знову MISS → HIT без рестарту backend (ADR 0043).

Біля кожного читання — інстанс, X-Cache, totalVotes, час відповіді, а також стан ключів у Redis (покоління і TTL),
прочитаний напряму через опублікований порт Redis. Скрипт сам зупиняє і завжди запускає Redis знову (`finally`).

Запуск з кореня репозиторію (стек піднятий):  python scripts/cache-demo.py [--pause]
  --pause  чекати Enter перед кожним кроком — зручно на захисті, щоб пояснювати по ходу.
Лише стандартна бібліотека Python. Вивід англійською — щоб не залежати від кодування консолі.
"""
import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

API = os.environ.get("API", "http://localhost:8080")
REDIS = os.environ.get("REDIS", "localhost:6379")
PASSWORD = "Password123!"
pause = False


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
            return resp.status, json.loads(raw) if raw else None, resp.headers, time.perf_counter() - started
    except urllib.error.HTTPError as err:
        raw = err.read()
        return err.code, json.loads(raw) if raw else None, err.headers, time.perf_counter() - started


def redis_cmd(*args):
    """Одна команда RESP через сокет; None, якщо Redis недоступний."""
    host, port = REDIS.split(":")
    payload = f"*{len(args)}\r\n" + "".join(f"${len(str(a).encode())}\r\n{a}\r\n" for a in args)
    try:
        with socket.create_connection((host, int(port)), timeout=1) as s:
            s.sendall(payload.encode())
            reply = s.recv(4096).decode()
    except OSError:
        return None
    # Коли контейнер зупинено, порт Docker приймає з'єднання і одразу закриває його без відповіді.
    if not reply:
        return None
    kind, rest = reply[0], reply[1:].split("\r\n")
    if kind == ":":
        return int(rest[0])
    if kind == "$":
        return None if rest[0] == "-1" else rest[1]
    return rest[0]


def redis_state(pid):
    gen = redis_cmd("GET", f"polling:results:gen:{pid}")
    if gen is None and redis_cmd("PING") is None:
        return "redis: unavailable"
    gen = gen or "0"
    ttl = redis_cmd("TTL", f"polling:results:v1:{pid}:g{gen}")
    return f"redis: gen={gen} TTL(g{gen})={'no entry' if ttl == -2 else f'{ttl}s'}"


def read(pid, label):
    status, body, headers, took = call("GET", f"/api/polls/{pid}/results")
    votes = body.get("totalVotes") if status == 200 else "-"
    poll_status = body.get("status") if status == 200 else "-"
    print(f"  {label:<26} {headers.get('X-Instance-ID', '?'):<10} HTTP {status}  X-Cache={headers.get('X-Cache', '-'):<6} "
          f"totalVotes={votes} status={poll_status:<6} {took * 1000:6.1f} ms   {redis_state(pid)}")
    return headers.get("X-Cache")


def step(title):
    print(f"\n=== {title} ===")
    if pause:
        input("  (Enter to continue) ")


def login(email):
    return call("POST", "/api/auth/login", body={"email": email, "password": PASSWORD})[1]["accessToken"]


def main():
    global pause
    parser = argparse.ArgumentParser()
    parser.add_argument("--pause", action="store_true", help="wait for Enter before each step")
    pause = parser.parse_args().pause

    author = login("user001@example.com")
    voters = [login(f"user{int(time.time()) % 400 + 50 + i:03d}@example.com") for i in range(2)]
    _, poll, _, _ = call("POST", "/api/polls", author, {
        "title": f"Cache demo {time.strftime('%H:%M:%S')}",
        "options": ["Yes", "No"],
        "endsAt": "2030-01-01T00:00:00Z",
    })
    pid, option = poll["id"], poll["options"][0]["id"]
    call("PATCH", f"/api/polls/{pid}/publish", author)
    print(f"Poll {pid} created and published via {API}")

    step("1. Cache Hit / Miss")
    read(pid, "first read (cold)")
    read(pid, "second read")
    read(pid, "third read")

    step("2. Invalidation on a mutation")
    status, _, headers, took = call("POST", f"/api/polls/{pid}/vote", voters[0], {"optionId": option})
    print(f"  {'POST vote':<26} {headers.get('X-Instance-ID', '?'):<10} HTTP {status}  {took * 1000:.1f} ms   {redis_state(pid)}")
    read(pid, "read after the vote")
    read(pid, "read again")
    status, _, headers, _ = call("PATCH", f"/api/polls/{pid}/close", author)
    print(f"  {'PATCH close':<26} {headers.get('X-Instance-ID', '?'):<10} HTTP {status}   {redis_state(pid)}")
    read(pid, "read after close")
    read(pid, "read again")

    # Для fallback потрібне активне опитування з голосуванням — нове, щоб кроки 2 і 3 не змішувались.
    _, poll, _, _ = call("POST", "/api/polls", author, {
        "title": f"Cache demo fallback {time.strftime('%H:%M:%S')}",
        "options": ["Yes", "No"],
        "endsAt": "2030-01-01T00:00:00Z",
    })
    pid, option = poll["id"], poll["options"][0]["id"]
    call("PATCH", f"/api/polls/{pid}/publish", author)
    read(pid, f"poll {pid}: warm the cache")
    read(pid, "read again")

    step("3. Fallback: docker compose stop redis")
    subprocess.run(["docker", "compose", "stop", "redis"], capture_output=True, check=True)
    try:
        read(pid, "read, Redis down")
        status, _, headers, took = call("POST", f"/api/polls/{pid}/vote", voters[1], {"optionId": option})
        print(f"  {'POST vote, Redis down':<26} {headers.get('X-Instance-ID', '?'):<10} HTTP {status}  {took * 1000:.1f} ms")
        read(pid, "read after the vote")
        status, body, _, _ = call("GET", "/health")
        print(f"  {'GET /health':<26} {'':<10} HTTP {status}  {body and body.get('status')} - nodes stay in the LB pool")
    finally:
        step("3. Fallback: docker compose start redis")
        subprocess.run(["docker", "compose", "start", "redis"], capture_output=True, check=True)

    deadline = time.monotonic() + 30
    while read(pid, "read, Redis back") == "BYPASS" and time.monotonic() < deadline:
        time.sleep(0.5)
    read(pid, "read again")
    return 0


if __name__ == "__main__":
    sys.exit(main())
