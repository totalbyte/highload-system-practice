"""Втрата інстансу під час голосування (лаба 2, П2-7).

Сценарій:
  1. Два свіжі опитування з allowVoteChange=false; 400 сід-користувачів голосують у кожному (800 голосів).
  2. Голоси йдуть паралельно (32 потоки), по черзі на backend-1 і backend-2.
  3. Коли виконано ~10 % голосів — `docker compose kill backend-1` (SIGKILL, аварійна зупинка);
     з прапорцем --stop — `docker compose stop backend-1` (штатна зупинка).
  4. Клієнт, не отримавши відповіді від backend-1, повторює той самий запит на backend-2 і далі шле
     запити backend-1 одразу на backend-2 — так у лабі 3 робитиме балансувальник (пасивний health check).
  5. Перевірки: кожен голос закінчився 201 або, при повторі, 409 — записано рівно один раз; рядків у votes =
     кількість користувачів; лічильники по варіантах узгоджені; результати backend-2 = БД.
     Окремо — що бачив PostgreSQL: обірвані з'єднання backend-1 і відкочені незавершені транзакції.
  6. Повернення інстансу: чи підняв його Docker сам (restart: unless-stopped); якщо ні — `docker compose start`.
     Далі /health = 200 і backend-1 одразу віддає ті самі результати — без «прогріву» стану.

Запуск з кореня репозиторію (стек піднятий):  python scripts/kill-test.py [--stop]
127.0.0.1, а не localhost: на Windows відмова в з'єднанні до localhost іде через IPv6 і IPv4 по черзі,
кожна з ~2 с повторів SYN. Вивід англійською — щоб не залежати від кодування консолі.
"""
import http.client
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

API1 = os.environ.get("API1", "http://127.0.0.1:8080")
API2 = os.environ.get("API2", "http://127.0.0.1:8082")
PASSWORD = "Password123!"
USERS = range(101, 501)          # 400 сід-користувачів
POLLS = 2                        # голосують у кожному з двох опитувань → 800 голосів
WORKERS = 32
PACE_SECONDS = 0.1               # пауза потоку між голосами: прогін ≈ 3 с, на backend-1 постійно щось у роботі
KILL_AFTER = len(USERS) * POLLS // 10
failures = 0


class NoResponse(Exception):
    """Інстанс не відповів: з'єднання відхилено, обірвано або таймаут."""


def call(base, method, path, token=None, body=None, timeout=10):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as err:          # відповідь отримано, просто не 2xx
        raw = err.read()
        return err.code, json.loads(raw) if raw else None
    except urllib.error.URLError as err:
        raise NoResponse(type(err.reason).__name__) from err
    # ConnectionError покриває Reset / Aborted (WinError 10053) / Refused; HTTPException — обрив посеред відповіді.
    except (ConnectionError, TimeoutError, http.client.HTTPException) as err:
        raise NoResponse(type(err).__name__) from err


def compose(*args, check=True):
    return subprocess.run(["docker", "compose", *args], capture_output=True, text=True, check=check).stdout.strip()


def sql(query):
    return compose("exec", "-T", "postgres", "psql", "-U", "polling", "-d", "polling", "-tAc", query)


def container_running(service):
    cid = compose("ps", "-aq", service)
    return subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", cid],
                          capture_output=True, text=True).stdout.strip() == "true"


def check(name, ok, detail=""):
    global failures
    failures += 0 if ok else 1
    print(f"  {'OK  ' if ok else 'FAIL'} {name:<60} {detail}")


def login(number):
    status, body = call(API2, "POST", "/api/auth/login",
                        body={"email": f"user{number:03d}@example.com", "password": PASSWORD})
    if status != 200:
        sys.exit(f"login failed for user{number:03d}: HTTP {status}")
    return body["accessToken"]


def wait_healthy(base, seconds=60):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if call(base, "GET", "/health", timeout=3)[0] == 200:
                return True
        except NoResponse:
            pass
        time.sleep(0.5)
    return False


def results_by_option(base, poll_id):
    status, body = call(base, "GET", f"/api/polls/{poll_id}/results")
    return status, (",".join(str(o["votes"]) for o in body["options"]) if status == 200 else None)


def db_by_option(poll_id):
    return sql(f"SELECT string_agg((SELECT count(*) FROM votes v WHERE v.option_id = o.id)::text, ',' "
               f"ORDER BY o.position) FROM options o WHERE o.poll_id = {poll_id}")


def new_poll(author):
    _, poll = call(API2, "POST", "/api/polls", author, {
        "title": f"Kill test {int(time.time() * 1000)}", "options": ["A", "B", "C"],
        "endsAt": "2030-01-01T00:00:00Z", "allowVoteChange": False})
    _, poll = call(API2, "PATCH", f"/api/polls/{poll['id']}/publish", author)
    return poll["id"], [o["id"] for o in poll["options"]]


def main():
    mode = "stop" if "--stop" in sys.argv else "kill"
    if not (wait_healthy(API1, 5) and wait_healthy(API2, 5)):
        sys.exit("both instances must be healthy before the test")

    author = login(1)
    polls = [new_poll(author) for _ in range(POLLS)]
    with ThreadPoolExecutor(32) as pool:
        tokens = list(pool.map(login, USERS))
    tasks = [(u, p) for p in range(POLLS) for u in range(len(tokens))]   # спершу всі голоси в опитування 0

    outcome = {}           # task -> (sent to, first status | error name, retry status | None)
    done, lock = [0], threading.Lock()
    kill_fired, backend1_down = threading.Event(), threading.Event()
    kill_info = {}

    def crash():
        kill_info["wall"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        kill_info["at"] = time.monotonic()
        compose(mode, "backend-1")
        kill_info["done"] = time.monotonic()

    def vote(n):
        u, p = tasks[n]
        poll_id, options = polls[p]
        token, body = tokens[u], {"optionId": options[u % len(options)]}
        path = f"/api/polls/{poll_id}/vote"
        if n % 2 == 1:
            outcome[n] = ("backend-2", call(API2, "POST", path, token, body)[0], None)
        elif backend1_down.is_set():
            outcome[n] = ("rerouted", call(API2, "POST", path, token, body)[0], None)
        else:
            try:
                outcome[n] = ("backend-1", call(API1, "POST", path, token, body)[0], None)
            except NoResponse as err:
                backend1_down.set()
                outcome[n] = ("backend-1", str(err), call(API2, "POST", path, token, body)[0])
        with lock:
            done[0] += 1
            if done[0] == KILL_AFTER and not kill_fired.is_set():
                kill_fired.set()
                threading.Thread(target=crash).start()
        time.sleep(PACE_SECONDS)

    print(f"Voting: {len(tokens)} users x {POLLS} polls = {len(tasks)} votes over {WORKERS} threads; "
          f"`docker compose {mode} backend-1` after {KILL_AFTER} votes")
    started = time.monotonic()
    with ThreadPoolExecutor(WORKERS) as pool:
        list(pool.map(vote, range(len(tasks))))
    while "done" not in kill_info:
        time.sleep(0.1)
    print(f"  run took {time.monotonic() - started:.1f}s; the {mode} command took "
          f"{kill_info['done'] - kill_info['at']:.1f}s")

    by_route = {r: sum(1 for o in outcome.values() if o[0] == r) for r in ("backend-1", "backend-2", "rerouted")}
    retried = [o for o in outcome.values() if o[2] is not None]
    print(f"  answered by backend-1: {by_route['backend-1'] - len(retried)}, by backend-2: {by_route['backend-2']}, "
          f"failed on backend-1 and retried on backend-2: {len(retried)} {sorted({o[1] for o in retried})}, "
          f"rerouted to backend-2 after that: {by_route['rerouted']}")

    pg = compose("logs", "--since", kill_info["wall"], "postgres")
    broken = pg.count("could not receive data from client") + pg.count("unexpected EOF on client connection")
    open_tx = pg.count("with an open transaction")
    print(f"  PostgreSQL saw {broken} client connection(s) break; of them with an open transaction "
          f"(rolled back): {open_tx}")

    print("\nChecks")
    check(f"backend-1 died mid-run and the client failed over", len(retried) > 0 and by_route["rerouted"] > 0,
          f"retried={len(retried)}, rerouted={by_route['rerouted']}")
    final = {n: (o[2] if o[2] is not None else o[1]) for n, o in outcome.items()}
    bad = {n: s for n, s in final.items() if not (s == 201 or (s == 409 and outcome[n][2] is not None))}
    retry_409 = sum(1 for o in retried if o[2] == 409)
    check("every vote ended with 201, or 409 on a retry", not bad,
          f"201x{list(final.values()).count(201)}, 409x{retry_409}, other={sorted(set(bad.values()))}")
    for poll_id, _ in polls:
        rows = sql(f"SELECT count(*) FROM votes WHERE poll_id = {poll_id}")
        check(f"poll {poll_id}: vote rows = users (stored exactly once)", rows == str(len(tokens)), f"rows={rows}")
    mismatches = sql("SELECT count(*) FROM options o WHERE o.vote_count <> "
                     "(SELECT count(*) FROM votes v WHERE v.option_id = o.id)")
    check("per-option counters = votes rows (whole DB)", mismatches == "0", f"mismatches={mismatches}")
    db = {poll_id: db_by_option(poll_id) for poll_id, _ in polls}
    seen = {poll_id: results_by_option(API2, poll_id)[1] for poll_id, _ in polls}
    check("results on backend-2 match the DB", seen == db, f"db={list(db.values())} backend-2={list(seen.values())}")

    print("\nInstance comes back")
    time.sleep(10)
    auto = container_running("backend-1")
    print(f"  Docker restarted backend-1 by itself within 10 s: {'yes' if auto else 'no'} (restart: unless-stopped)")
    if not auto:
        compose("start", "backend-1")
        print("  -> docker compose start backend-1")
    back = time.monotonic()
    check("backend-1 /health = 200", wait_healthy(API1), f"after {time.monotonic() - back:.1f}s")
    seen1 = {poll_id: results_by_option(API1, poll_id)[1] for poll_id, _ in polls}
    check("backend-1 serves the same results right away (no warm-up)", seen1 == db, f"backend-1={list(seen1.values())}")

    print(f"\n{'ALL CHECKS PASSED' if failures == 0 else f'{failures} CHECK(S) FAILED'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    try:
        main()
    finally:
        if not container_running("backend-1"):
            compose("start", "backend-1", check=False)
