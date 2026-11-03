"""Поведінка при недоступному Redis: fallback на БД (лаба 4, П1-5, ADR 0043; до лаби 4 — 503, ADR 0027).

Прогріває кеш, зупиняє контейнер redis (`docker stop redis` з методички) і перевіряє, що:
  - читання результатів дає 200 з `X-Cache: BYPASS` — прямо з БД — і швидко, без очікування таймауту Redis;
  - голос записується в БД рівно раз, клієнт отримує 201, і наступне читання вже його бачить;
  - publish проходить (збій інвалідації не валить запит), і щойно опублікована чернетка видна стороннім;
  - балансувальник не виключає вузли (/health не залежить від Redis) і лічильники по варіантах узгоджені;
  - після запуску redis — знову кеш (MISS / HIT, а не BYPASS) без рестарту backend, результати свіжі:
    Redis повертається порожнім, тож прогрітий до збою застарілий запис не воскресає.

Запуск з кореня репозиторію (стек піднятий):  python scripts/redis-outage-check.py
З лаби 3 обидві адреси за замовчуванням — балансувальник (backend-и не публікують портів, ADR 0031): запити
розподіляє HAProxy.
Вивід англійською — щоб не залежати від кодування консолі.
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

API1 = os.environ.get("API1", "http://localhost:8080")
API2 = os.environ.get("API2", "http://localhost:8080")
PASSWORD = "Password123!"
failures = 0


def call(base, method, path, token=None, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else None, time.monotonic() - started, resp.headers
    except urllib.error.HTTPError as err:
        raw = err.read()
        return err.code, json.loads(raw) if raw else None, time.monotonic() - started, err.headers


def compose(*args):
    return subprocess.run(["docker", "compose", *args], capture_output=True, text=True, check=True).stdout.strip()


def sql(query):
    return compose("exec", "-T", "postgres", "psql", "-U", "polling", "-d", "polling", "-tAc", query)


def login(email):
    return call(API1, "POST", "/api/auth/login", body={"email": email, "password": PASSWORD})[1]["accessToken"]


def check(name, ok, detail=""):
    global failures
    failures += 0 if ok else 1
    print(f"  {'OK  ' if ok else 'FAIL'} {name:<58} {detail}")


def new_poll(token, publish=True):
    _, poll, _, _ = call(API1, "POST", "/api/polls", token, {
        "title": f"Redis outage {int(time.time() * 1000)}",
        "options": ["Yes", "No"],
        "endsAt": "2030-01-01T00:00:00Z",
    })
    if publish:
        _, poll, _, _ = call(API1, "PATCH", f"/api/polls/{poll['id']}/publish", token)
    return poll


def backend_started_at():
    return [compose("ps", "-q", s) for s in ("backend-1", "backend-2")], [
        subprocess.run(["docker", "inspect", "-f", "{{.State.StartedAt}}", compose("ps", "-q", s)],
                       capture_output=True, text=True, check=True).stdout.strip()
        for s in ("backend-1", "backend-2")]


def main():
    author = login("user001@example.com")
    voter = login(f"user{int(time.time()) % 400 + 50:03d}@example.com")
    poll = new_poll(author)
    pid, option = poll["id"], poll["options"][0]["id"]
    draft = new_poll(author, publish=False)
    _, started_before = backend_started_at()

    # Якщо Redis щойно перезапустили, клієнти backend перепідключаються ~2 с і читання ще йдуть BYPASS. Чекаємо,
    # поки кеш доступний на обох інстансах (кілька читань поспіль через балансувальник), — на гарячому опитуванні #1,
    # щоб не прогріти опитування, яке перевіряємо далі.
    deadline, in_a_row = time.monotonic() + 30, 0
    while in_a_row < 4 and time.monotonic() < deadline:
        in_a_row = in_a_row + 1 if call(API2, "GET", "/api/polls/1/results")[3].get("X-Cache") != "BYPASS" else 0
        time.sleep(0.2 if in_a_row == 0 else 0)

    print("Redis up: warm the cache")
    call(API2, "GET", f"/api/polls/{pid}/results")
    status, body, _, headers = call(API2, "GET", f"/api/polls/{pid}/results")
    check("GET results -> 200 HIT, totalVotes=0", status == 200 and headers.get("X-Cache") == "HIT"
          and body["totalVotes"] == 0, f"HTTP {status} X-Cache={headers.get('X-Cache')}")
    status, _, _, _ = call(API1, "GET", f"/api/polls/{draft['id']}/results", author)
    check("author reads own draft (cached as draft)", status == 200, f"HTTP {status}")

    print("\nRedis stopped (docker compose stop redis)")
    compose("stop", "redis")
    try:
        status, body, took, headers = call(API2, "GET", f"/api/polls/{pid}/results")
        check("GET results -> 200 BYPASS (read from PostgreSQL)", status == 200 and headers.get("X-Cache") == "BYPASS",
              f"HTTP {status} X-Cache={headers.get('X-Cache')} in {took * 1000:.0f} ms")
        check("  ... without waiting for a Redis timeout", took < 1, f"{took * 1000:.0f} ms")

        status, _, took, _ = call(API1, "POST", f"/api/polls/{pid}/vote", voter, {"optionId": option})
        check("POST vote -> 201 (committed vote not reported as failed)", status == 201,
              f"HTTP {status} in {took * 1000:.0f} ms")
        rows = sql(f"SELECT count(*) FROM votes WHERE poll_id = {pid}")
        check("vote stored in PostgreSQL exactly once", rows == "1", f"rows={rows}")
        status, body, _, headers = call(API2, "GET", f"/api/polls/{pid}/results")
        check("next read sees the vote (BYPASS, totalVotes=1)", status == 200 and body["totalVotes"] == 1,
              f"X-Cache={headers.get('X-Cache')} totalVotes={body and body.get('totalVotes')}")

        status, _, took, _ = call(API1, "PATCH", f"/api/polls/{draft['id']}/publish", author)
        check("PATCH publish -> 200 (failed invalidation tolerated)", status == 200,
              f"HTTP {status} in {took * 1000:.0f} ms")
        status, body, _, _ = call(API2, "GET", f"/api/polls/{draft['id']}/results")
        check("just-published poll visible to others (not a stale 404)", status == 200 and body["status"] == "active",
              f"HTTP {status}")

        status, body, _, _ = call(API1, "GET", "/health")
        check("/health 200 - nodes stay in the LB pool", status == 200, f"HTTP {status}")
        bad = sql("SELECT count(*) FROM options o WHERE o.vote_count <> "
                  "(SELECT count(*) FROM votes v WHERE v.option_id = o.id)")
        check("per-option counters consistent", bad == "0", f"mismatches={bad}")
    finally:
        print("\nRedis started again (docker compose start redis)")
        compose("start", "redis")

    deadline, status, headers = time.monotonic() + 30, None, {}
    started = time.monotonic()
    while time.monotonic() < deadline:
        status, body, _, headers = call(API2, "GET", f"/api/polls/{pid}/results")
        if status == 200 and headers.get("X-Cache") != "BYPASS":
            break
        time.sleep(0.2)
    # Перше читання з кешем після рестарту — MISS: Redis повернувся порожнім. HIT означав би, що з диска воскрес
    # прогрітий до збою запис, інвалідацію якого Redis пропустив (totalVotes=0).
    check("cache used again, first read MISS (Redis came back empty)", headers.get("X-Cache") == "MISS",
          f"X-Cache={headers.get('X-Cache')} after {time.monotonic() - started:.1f}s")
    check("results are fresh (the outage vote is counted)", status == 200 and body["totalVotes"] == 1,
          f"totalVotes={body and body.get('totalVotes')}")
    _, started_after = backend_started_at()
    check("no backend restart", started_before == started_after)

    print(f"\n{'ALL CHECKS PASSED' if failures == 0 else f'{failures} CHECK(S) FAILED'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
