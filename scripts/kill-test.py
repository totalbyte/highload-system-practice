"""Втрата інстансу під час голосування через балансувальник (лаба 2 П2-7 → лаба 3 П2-4).

Сценарій:
  1. Два свіжі опитування з allowVoteChange=false; 400 сід-користувачів голосують у кожному (800 голосів).
  2. Голоси йдуть паралельно (32 потоки) на балансувальник — вузол обирає HAProxy, клієнт інстансів не знає.
  3. Коли виконано ~10 % голосів — `docker compose kill backend-1` (SIGKILL, аварійна зупинка);
     з прапорцем --stop — `docker compose stop backend-1` (SIGTERM: ASP.NET доробляє поточні запити).
  4. Що бачить клієнт: кожна відповідь 5xx або обрив з'єднання рахується як помилка, яку отримав би користувач.
     Після помилки клієнт один раз повторює той самий голос (як зробила б людина) — щоб перевірити, що голос
     записано рівно один раз: повтор дає 201 або 409, якщо перша спроба встигла закомітитись.
  5. Скільки секунд HAProxy ще вважав backend-1 живим (сторінка статистики) і скільки голосів за цей час обробив
     backend-2 (X-Instance-ID).
  6. Перевірки цілісності — як у лабі 2: рядків у votes = користувачів, лічильники по варіантах узгоджені,
     результати = БД; що бачив PostgreSQL (обірвані з'єднання, відкочені транзакції).
  7. Повернення: `docker compose start backend-1`, HAProxy повертає вузол у пул сам, результати ті самі.

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

API = os.environ.get("API", "http://127.0.0.1:8080")
STATS = os.environ.get("LB_STATS", "http://127.0.0.1:8404/stats;csv")
PASSWORD = "Password123!"
USERS = range(101, 501)          # 400 сід-користувачів
POLLS = 2                        # голосують у кожному з двох опитувань → 800 голосів
WORKERS = 32
PACE_SECONDS = 0.1               # пауза потоку між голосами: прогін ≈ 3 с, на backend-1 постійно щось у роботі
KILL_AFTER = len(USERS) * POLLS // 10
failures = 0


def call(method, path, token=None, body=None, timeout=35):
    """(status | назва помилки з'єднання, тіло, X-Instance-ID). Таймаут більший за timeout server HAProxy (30 с)."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None), resp.headers.get("X-Instance-ID")
    except urllib.error.HTTPError as err:          # відповідь отримано, просто не 2xx
        raw = err.read()
        try:
            parsed = json.loads(raw) if raw else None
        except ValueError:                         # HTML-сторінка помилки HAProxy, а не наш ProblemDetails
            parsed = None
        return err.code, parsed, err.headers.get("X-Instance-ID")
    except urllib.error.URLError as err:
        return type(err.reason).__name__, None, None
    except (ConnectionError, TimeoutError, http.client.HTTPException) as err:
        return type(err).__name__, None, None


def is_error(status):
    return not isinstance(status, int) or status >= 500


def compose(*args, check=True):
    return subprocess.run(["docker", "compose", *args], capture_output=True, text=True, check=check).stdout.strip()


def sql(query):
    return compose("exec", "-T", "postgres", "psql", "-U", "polling", "-d", "polling", "-tAc", query)


def container_running(service):
    cid = compose("ps", "-aq", service)
    return subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", cid],
                          capture_output=True, text=True).stdout.strip() == "true"


def lb_state(server, backend="be_api"):
    """Стан вузла в секції HAProxy: UP / DOWN / ... (стовпець status у CSV статистики)."""
    try:
        with urllib.request.urlopen(STATS, timeout=3) as resp:
            for line in resp.read().decode().splitlines():
                cols = line.split(",")
                if cols[0] == backend and cols[1] == server:
                    return cols[17]
    except OSError:
        pass
    return "?"


def wait_lb(server, prefix, seconds=60, backend="be_api"):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if lb_state(server, backend).startswith(prefix):
            return True
        time.sleep(0.2)
    return False


def check(name, ok, detail=""):
    global failures
    failures += 0 if ok else 1
    print(f"  {'OK  ' if ok else 'FAIL'} {name:<60} {detail}")


def login(number):
    status, body, _ = call("POST", "/api/auth/login",
                           body={"email": f"user{number:03d}@example.com", "password": PASSWORD})
    if status != 200:
        sys.exit(f"login failed for user{number:03d}: {status}")
    return body["accessToken"]


def results_by_option(poll_id):
    status, body, instance = call("GET", f"/api/polls/{poll_id}/results")
    return (",".join(str(o["votes"]) for o in body["options"]) if status == 200 else status), instance


def db_by_option(poll_id):
    return sql(f"SELECT string_agg((SELECT count(*) FROM votes v WHERE v.option_id = o.id)::text, ',' "
               f"ORDER BY o.position) FROM options o WHERE o.poll_id = {poll_id}")


def new_poll(author):
    _, poll, _ = call("POST", "/api/polls", author, {
        "title": f"Kill test {int(time.time() * 1000)}", "options": ["A", "B", "C"],
        "endsAt": "2030-01-01T00:00:00Z", "allowVoteChange": False})
    _, poll, _ = call("PATCH", f"/api/polls/{poll['id']}/publish", author)
    return poll["id"], [o["id"] for o in poll["options"]]


def main():
    mode = "stop" if "--stop" in sys.argv else "kill"
    if not (wait_lb("backend-1", "UP", 5) and wait_lb("backend-2", "UP", 5)):
        sys.exit("backend-1 and backend-2 must be UP in HAProxy before the test")

    author = login(1)
    polls = [new_poll(author) for _ in range(POLLS)]
    with ThreadPoolExecutor(32) as pool:
        tokens = list(pool.map(login, USERS))
    tasks = [(u, p) for p in range(POLLS) for u in range(len(tokens))]   # спершу всі голоси в опитування 0

    outcome = {}           # task -> (first status | error name, instance, retry status | None, time since kill)
    done, lock = [0], threading.Lock()
    kill_fired = threading.Event()
    kill_info = {}

    def crash():
        kill_info["wall"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        kill_info["at"] = time.monotonic()
        compose(mode, "backend-1")
        kill_info["done"] = time.monotonic()
        # Скільки HAProxy ще тримав мертвий вузол у пулі: голоси йдуть через be_vote (ADR 0037), решта — be_api.
        threading.Thread(target=lambda: wait_lb("backend-1", "DOWN", 60, "be_vote")
                         and kill_info.setdefault("vote_down", time.monotonic())).start()
        wait_lb("backend-1", "DOWN", 60)
        kill_info["down"] = time.monotonic()

    def vote(n):
        u, p = tasks[n]
        poll_id, options = polls[p]
        token, body = tokens[u], {"optionId": options[u % len(options)]}
        path = f"/api/polls/{poll_id}/vote"
        status, _, instance = call("POST", path, token, body)
        retry = call("POST", path, token, body)[0] if is_error(status) else None
        since_kill = time.monotonic() - kill_info["at"] if "at" in kill_info else None
        outcome[n] = (status, instance, retry, since_kill)
        with lock:
            done[0] += 1
            if done[0] == KILL_AFTER and not kill_fired.is_set():
                kill_fired.set()
                threading.Thread(target=crash).start()
        time.sleep(PACE_SECONDS)

    print(f"Voting: {len(tokens)} users x {POLLS} polls = {len(tasks)} votes over {WORKERS} threads through {API}; "
          f"`docker compose {mode} backend-1` after {KILL_AFTER} votes")
    started = time.monotonic()
    with ThreadPoolExecutor(WORKERS) as pool:
        list(pool.map(vote, range(len(tasks))))
    while "down" not in kill_info:
        time.sleep(0.1)
    print(f"  run took {time.monotonic() - started:.1f}s; the {mode} command took "
          f"{kill_info['done'] - kill_info['at']:.1f}s; HAProxy marked backend-1 DOWN after the {mode} started: "
          f"be_vote {kill_info['vote_down'] - kill_info['at'] if 'vote_down' in kill_info else float('nan'):.1f}s, "
          f"be_api {kill_info['down'] - kill_info['at']:.1f}s")

    errors = {n: o for n, o in outcome.items() if is_error(o[0])}
    by_instance = {}
    for o in outcome.values():
        by_instance[o[1] or "-"] = by_instance.get(o[1] or "-", 0) + 1
    error_kinds = {}
    for o in errors.values():
        error_kinds[o[0]] = error_kinds.get(o[0], 0) + 1
    window = [o[3] for o in errors.values() if o[3] is not None]
    print(f"  answered by: {dict(sorted(by_instance.items()))}")
    print(f"  errors the client saw: {len(errors)} {dict(sorted(error_kinds.items(), key=str))}"
          + (f", {min(window):.1f}-{max(window):.1f}s after the {mode}" if window else ""))

    pg = compose("logs", "--since", kill_info["wall"], "postgres")
    broken = pg.count("could not receive data from client") + pg.count("unexpected EOF on client connection")
    open_tx = pg.count("with an open transaction")
    print(f"  PostgreSQL saw {broken} client connection(s) break; of them with an open transaction "
          f"(rolled back): {open_tx}")

    print("\nChecks")
    check("no 5xx / connection errors seen by the client", not errors, f"errors={len(errors)}")
    # 409 без помилки перед ним — HAProxy сам повторив голос, який уже закомітився на вбитому вузлі (be_vote,
    # ADR 0037): відповідь загубилась, повтор отримав «вже голосували». Голос є рівно один — це перевіряють рядки нижче.
    final = {n: (o[2] if o[2] is not None else o[0]) for n, o in outcome.items()}
    bad = {n: s for n, s in final.items() if s not in (201, 409)}
    retry_409 = sum(1 for o in errors.values() if o[2] == 409)
    lb_409 = sum(1 for o in outcome.values() if o[0] == 409)
    check("every vote ended with 201, or 409 = already stored", not bad,
          f"201x{list(final.values()).count(201)}, 409 after an HAProxy retry x{lb_409}, "
          f"409 on a client retry x{retry_409}, other={sorted(set(map(str, bad.values())))}")
    for poll_id, _ in polls:
        rows = sql(f"SELECT count(*) FROM votes WHERE poll_id = {poll_id}")
        check(f"poll {poll_id}: vote rows = users (stored exactly once)", rows == str(len(tokens)), f"rows={rows}")
    mismatches = sql("SELECT count(*) FROM options o WHERE o.vote_count <> "
                     "(SELECT count(*) FROM votes v WHERE v.option_id = o.id)")
    check("per-option counters = votes rows (whole DB)", mismatches == "0", f"mismatches={mismatches}")
    db = {poll_id: db_by_option(poll_id) for poll_id, _ in polls}
    seen = {poll_id: results_by_option(poll_id)[0] for poll_id, _ in polls}
    check("results through the balancer match the DB", seen == db, f"db={list(db.values())} lb={list(seen.values())}")

    print("\nInstance comes back")
    compose("start", "backend-1")
    back = time.monotonic()
    check("HAProxy put backend-1 back into the pool (UP)", wait_lb("backend-1", "UP"),
          f"after {time.monotonic() - back:.1f}s")
    served = {}
    for poll_id, _ in polls:
        for _ in range(10):                         # читаємо, доки не відповість саме backend-1
            value, instance = results_by_option(poll_id)
            served.setdefault(instance, set()).add(value == db[poll_id])
            if instance == "backend-1":
                break
    check("backend-1 serves the same results right away (no warm-up)", served.get("backend-1") == {True},
          f"by instance: {{{', '.join(f'{k}: {sorted(v)}' for k, v in sorted(served.items(), key=str))}}}")

    print(f"\n{'ALL CHECKS PASSED' if failures == 0 else f'{failures} CHECK(S) FAILED'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    try:
        main()
    finally:
        if not container_running("backend-1"):
            compose("start", "backend-1", check=False)
