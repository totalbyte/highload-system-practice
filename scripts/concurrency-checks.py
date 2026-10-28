"""Три перевірки паралельного голосування на двох інстансах (лаба 2, П2-6).

Запити діляться навпіл між backend-1 і backend-2 і стартують одночасно (бар'єр), тож конкурують
між собою і через різні процеси, і в одному процесі. З лаби 3 обидві адреси за замовчуванням — балансувальник
(ADR 0031): навпіл їх ділить уже HAProxy, а не скрипт.

  1. Багато різних користувачів голосують в одне опитування одночасно → усі 201, жодного 5xx.
  2. Один користувач паралельно змінює голос (allowVoteChange) → усі 200, рівно один рядок голосу.
     На свіжому опитуванні (малі лічильники) і на «гарячому» опитуванні #1 (великі лічильники).
  3. Зустрічні зміни A→B і B→A одночасно → усі 200, жодного deadlock у логах postgres.

Після кожної перевірки: лічильники по кожному варіанту = кількість рядків у votes (не сумою — ADR 0017),
і результати з обох інстансів збігаються з БД (кеш у Redis спільний — ADR 0026).
Наприкінці: у логах postgres немає «deadlock detected», у логах backend — записів fail:.

Запуск з кореня репозиторію (стек піднятий):  python scripts/concurrency-checks.py
Вивід англійською — щоб не залежати від кодування консолі.
"""
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

INSTANCES = [os.environ.get("API1", "http://localhost:8080"), os.environ.get("API2", "http://localhost:8080")]
PASSWORD = "Password123!"
failures = 0


def call(base, method, path, token=None, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as err:
        raw = err.read()
        return err.code, json.loads(raw) if raw else None


def compose(*args):
    return subprocess.run(["docker", "compose", *args], capture_output=True, text=True, check=True).stdout


def sql(query):
    return compose("exec", "-T", "postgres", "psql", "-U", "polling", "-d", "polling", "-tAc", query).strip()


def check(name, ok, detail=""):
    global failures
    failures += 0 if ok else 1
    print(f"  {'OK  ' if ok else 'FAIL'} {name:<52} {detail}")


def login(user_number):
    status, body = call(INSTANCES[0], "POST", "/api/auth/login",
                        body={"email": f"user{user_number:03d}@example.com", "password": PASSWORD})
    if status != 200:
        sys.exit(f"login failed for user{user_number:03d}: HTTP {status}")
    return body["accessToken"]


def login_many(numbers):
    with ThreadPoolExecutor(32) as pool:
        return list(pool.map(login, numbers))


def new_poll(author, title, allow_change):
    _, poll = call(INSTANCES[0], "POST", "/api/polls", author, {
        "title": f"{title} {int(time.time() * 1000)}",
        "options": ["A", "B"],
        "endsAt": "2030-01-01T00:00:00Z",
        "allowVoteChange": allow_change,
    })
    _, poll = call(INSTANCES[0], "PATCH", f"/api/polls/{poll['id']}/publish", author)
    return poll["id"], [o["id"] for o in poll["options"]]


def options_of(poll_id):
    _, poll = call(INSTANCES[0], "GET", f"/api/polls/{poll_id}")
    return [o["id"] for o in poll["options"]]


def burst(requests):
    """Запускає всі запити одночасно; i-й запит іде на інстанс i % 2. Повертає список HTTP-кодів."""
    barrier = threading.Barrier(len(requests))

    def run(indexed):
        i, (token, poll_id, option_id) = indexed
        barrier.wait()
        return call(INSTANCES[i % 2], "POST", f"/api/polls/{poll_id}/vote", token, {"optionId": option_id})[0]

    with ThreadPoolExecutor(len(requests)) as pool:
        return list(pool.map(run, enumerate(requests)))


def codes_summary(codes):
    return ", ".join(f"{c}x{codes.count(c)}" for c in sorted(set(codes)))


def invariants(poll_id):
    """Лічильники по варіантах у всій БД, і результати з обох інстансів = дані БД для цього опитування."""
    bad = sql("SELECT count(*) FROM options o WHERE o.vote_count <> "
              "(SELECT count(*) FROM votes v WHERE v.option_id = o.id)")
    check("per-option counters = votes rows (whole DB)", bad == "0", f"mismatches={bad}")
    db_votes = sql(f"SELECT string_agg((SELECT count(*) FROM votes v WHERE v.option_id = o.id)::text, ',' "
                   f"ORDER BY o.position) FROM options o WHERE o.poll_id = {poll_id}")
    seen = []
    for base in INSTANCES:
        _, results = call(base, "GET", f"/api/polls/{poll_id}/results")
        seen.append(",".join(str(o["votes"]) for o in results["options"]))
    check("results from two reads (any instances) match the DB", seen == [db_votes, db_votes],
          f"db={db_votes} b1={seen[0]} b2={seen[1]}")


def main():
    started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    author = login(1)

    print("Check 1: 200 different users vote into one poll at once")
    poll_id, options = new_poll(author, "Concurrency 1", allow_change=False)
    voters = login_many(range(101, 301))
    codes = burst([(t, poll_id, options[i % 2]) for i, t in enumerate(voters)])
    check("all 201, no 5xx", codes.count(201) == len(voters), codes_summary(codes))
    rows = sql(f"SELECT count(*) FROM votes WHERE poll_id = {poll_id}")
    check("one vote row per user", rows == str(len(voters)), f"rows={rows}")
    invariants(poll_id)

    print("\nCheck 2: one user changes the vote 40 times in parallel")
    user_number, token = 450, login(450)
    fresh_id, fresh_options = new_poll(author, "Concurrency 2", allow_change=True)
    for label, target_id, target_options in (("fresh poll", fresh_id, fresh_options), ("hot poll #1", 1, options_of(1))):
        call(INSTANCES[0], "POST", f"/api/polls/{target_id}/vote", token, {"optionId": target_options[0]})
        codes = burst([(token, target_id, target_options[(i + 1) % 2]) for i in range(40)])
        check(f"{label}: all 200", codes.count(200) == 40, codes_summary(codes))
        rows = sql(f"SELECT count(*) FROM votes v JOIN users u ON u.id = v.user_id "
                   f"WHERE v.poll_id = {target_id} AND u.email = 'user{user_number:03d}@example.com'")
        check(f"{label}: exactly one vote row for the user", rows == "1", f"rows={rows}")
        invariants(target_id)

    print("\nCheck 3: 100 users make opposite changes (A->B and B->A) at once")
    poll_id, options = new_poll(author, "Concurrency 3", allow_change=True)
    users = login_many(range(301, 401))
    first = burst([(t, poll_id, options[i % 2]) for i, t in enumerate(users)])
    check("initial votes: all 201", first.count(201) == len(users), codes_summary(first))
    codes = burst([(t, poll_id, options[(i + 1) % 2]) for i, t in enumerate(users)])
    check("opposite changes: all 200", codes.count(200) == len(users), codes_summary(codes))
    split = sql(f"SELECT string_agg(vote_count::text, '/' ORDER BY position) FROM options WHERE poll_id = {poll_id}")
    check("still 50/50 after the swap", split == "50/50", split)
    invariants(poll_id)

    print("\nLogs since the start of this run")
    deadlocks = compose("logs", "--since", started_at, "postgres").count("deadlock detected")
    check("no 'deadlock detected' in postgres logs", deadlocks == 0, f"count={deadlocks}")
    backend_fails = compose("logs", "--since", started_at, "backend-1", "backend-2").count("fail:")
    check("no 'fail:' entries in backend logs", backend_fails == 0, f"count={backend_fails}")

    print(f"\n{'ALL CHECKS PASSED' if failures == 0 else f'{failures} CHECK(S) FAILED'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
