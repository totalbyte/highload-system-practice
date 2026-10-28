"""Поведінка при недоступному Redis (лаба 2, П2-4, ADR 0027).

Зупиняє контейнер redis і перевіряє, що:
  - читання результатів дає 503 (не 500), з ProblemDetails;
  - голос записується в БД і клієнт отримує 201, а не помилку на вже закомічений голос;
  - publish проходить (збій інвалідації кешу не валить запит);
  - лічильники по варіантах узгоджені;
  - після запуску redis усе працює без рестарту backend і результати свіжі.

Запуск з кореня репозиторію (стек піднятий):  python scripts/redis-outage-check.py
З лаби 3 обидві адреси за замовчуванням — балансувальник (backend-и не публікують портів, ADR 0031): запити
розподіляє HAProxy. Тож перевіряється ще й те, що клієнт бачить 503 від API, а не сторінку помилки балансувальника.
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
            return resp.status, json.loads(raw) if raw else None, time.monotonic() - started
    except urllib.error.HTTPError as err:
        raw = err.read()
        return err.code, json.loads(raw) if raw else None, time.monotonic() - started


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
    _, poll, _ = call(API1, "POST", "/api/polls", token, {
        "title": f"Redis outage {int(time.time() * 1000)}",
        "options": ["Yes", "No"],
        "endsAt": "2030-01-01T00:00:00Z",
    })
    if publish:
        _, poll, _ = call(API1, "PATCH", f"/api/polls/{poll['id']}/publish", token)
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

    print("Redis up")
    status, _, _ = call(API2, "GET", f"/api/polls/{pid}/results")
    check("GET results", status == 200, f"HTTP {status}")

    print("\nRedis stopped (docker compose stop redis)")
    compose("stop", "redis")
    try:
        status, body, took = call(API2, "GET", f"/api/polls/{pid}/results")
        check("GET results -> 503 with ProblemDetails", status == 503 and body and body.get("status") == 503,
              f"HTTP {status} in {took:.1f}s, detail: {body and body.get('detail')}")

        status, _, took = call(API1, "POST", f"/api/polls/{pid}/vote", voter, {"optionId": option})
        check("POST vote -> 201 (committed vote not reported as failed)", status == 201, f"HTTP {status} in {took:.1f}s")
        rows = sql(f"SELECT count(*) FROM votes WHERE poll_id = {pid}")
        check("vote stored in PostgreSQL exactly once", rows == "1", f"rows={rows}")

        status, _, took = call(API1, "PATCH", f"/api/polls/{draft['id']}/publish", author)
        check("PATCH publish -> 200 (failed invalidation tolerated)", status == 200, f"HTTP {status} in {took:.1f}s")

        bad = sql("SELECT count(*) FROM options o WHERE o.vote_count <> "
                  "(SELECT count(*) FROM votes v WHERE v.option_id = o.id)")
        check("per-option counters consistent", bad == "0", f"mismatches={bad}")
    finally:
        print("\nRedis started again (docker compose start redis)")
        compose("start", "redis")

    deadline, status = time.monotonic() + 30, None
    started = time.monotonic()
    while time.monotonic() < deadline:
        status, body, _ = call(API2, "GET", f"/api/polls/{pid}/results")
        if status == 200:
            break
        time.sleep(0.5)
    check("GET results -> 200 again", status == 200, f"after {time.monotonic() - started:.1f}s")
    check("results are fresh (the outage vote is counted)", status == 200 and body["totalVotes"] == 1,
          f"totalVotes={body and body.get('totalVotes')}")
    _, started_after = backend_started_at()
    check("no backend restart", started_before == started_after)

    print(f"\n{'ALL CHECKS PASSED' if failures == 0 else f'{failures} CHECK(S) FAILED'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
