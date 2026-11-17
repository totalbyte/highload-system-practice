"""Перевірка реплікації для лаби 6 (пункт 2.1 і перший пункт процедури захисту).

  1. Топологія: хто Primary, хто Replica, стан потоку WAL (pg_stat_replication, слот, pg_stat_wal_receiver).
  2. Початковий стан: міграції і сід, застосовані лише на Primary, є і на Replica.
  3. Мутації через API (INSERT, UPDATE, DELETE) доходять до Replica; виводиться LSN запису і час до відтворення.
  4. Запис напряму в Replica відхиляється: вузол read-only.

Запуск з кореня репозиторію (стек піднятий):  python scripts/replication-check.py [--pause]
  --pause  чекати Enter перед кожним кроком — зручно на захисті, щоб пояснювати по ходу.
Лише стандартна бібліотека Python. Вивід англійською — щоб не залежати від кодування консолі.
Час до відтворення містить накладні витрати `docker compose exec`, тож це верхня межа, а не сама затримка реплікації.
Код виходу 0 — усі перевірки пройшли.
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
# Пара вузлів шарду, яку перевіряємо (лаба 7, ADR 0055): --shard A (як у лабі 6) або --shard B.
PAIRS = {"A": ("postgres", "postgres-replica"), "B": ("postgres-shard-b", "postgres-shard-b-replica")}
PRIMARY, REPLICA = PAIRS["A"]
SHARD = "A"
TABLES = ["users", "polls", "options", "votes", '"__EFMigrationsHistory"']
REPLAY_TIMEOUT_S = 10

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


def psql(service, query):
    """Один запит через psql у контейнері: (код виходу, stdout, stderr)."""
    done = subprocess.run(
        ["docker", "compose", "exec", "-T", service, "psql", "-U", "polling", "-d", "polling",
         "-v", "ON_ERROR_STOP=1", "-tA", "-c", query],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    return done.returncode, done.stdout.strip(), done.stderr.strip()


def scalar(service, query):
    code, out, err = psql(service, query)
    if code != 0:
        raise RuntimeError(f"{service}: {err}")
    return out


def call(method, path, token=None, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as err:
        raw = err.read()
        return err.code, json.loads(raw) if raw else None


def wait_replayed(lsn):
    """Секунди, поки Replica не відтворить LSN; None, якщо не встигла за REPLAY_TIMEOUT_S."""
    started = time.perf_counter()
    while time.perf_counter() - started < REPLAY_TIMEOUT_S:
        if scalar(REPLICA, f"SELECT pg_last_wal_replay_lsn() >= '{lsn}'::pg_lsn") == "t":
            return time.perf_counter() - started
        time.sleep(0.02)
    return None


def replicated(action, query, expected):
    """Після мутації на Primary: LSN запису, очікування Replica, той самий запит на обох вузлах."""
    lsn = scalar(PRIMARY, "SELECT pg_current_wal_lsn()")
    took = wait_replayed(lsn)
    timing = "not replayed in time" if took is None else f"replayed in {took * 1000:.0f} ms"
    print(f"  {action}: primary LSN {lsn}, {timing}")
    on_primary, on_replica = scalar(PRIMARY, query), scalar(REPLICA, query)
    print(f"    primary: {on_primary!r}   replica: {on_replica!r}")
    check(took is not None and on_primary == on_replica == expected, f"{action} is on the replica")


def topology():
    step("1. Topology")
    primary_role = scalar(PRIMARY, "SELECT pg_is_in_recovery()")
    replica_role = scalar(REPLICA, "SELECT pg_is_in_recovery()")
    print(f"  {PRIMARY}: pg_is_in_recovery = {primary_role}")
    print(f"  {REPLICA}: pg_is_in_recovery = {replica_role}")
    check(primary_role == "f", f"{PRIMARY} is the primary")
    check(replica_role == "t", f"{REPLICA} is a standby")

    stream = scalar(PRIMARY, "SELECT state, sync_state, sent_lsn, replay_lsn, "
                             "coalesce(replay_lag::text, 'idle') FROM pg_stat_replication")
    print(f"  pg_stat_replication (state|sync|sent|replay|lag): {stream or 'no rows'}")
    check(stream.startswith("streaming|async|"), "WAL is streaming asynchronously")

    slot = scalar(PRIMARY, "SELECT slot_name, active FROM pg_replication_slots")
    print(f"  pg_replication_slots (name|active): {slot or 'no rows'}")
    check(slot == "replica_1|t", "the replication slot is in use")

    receiver = scalar(REPLICA, "SELECT status, sender_host FROM pg_stat_wal_receiver")
    print(f"  pg_stat_wal_receiver (status|sender): {receiver or 'no rows'}")
    check(receiver.startswith("streaming|"), "the replica receives WAL")


def initial_state():
    step("2. Migrations and seed were applied on the primary only")
    wait_replayed(scalar(PRIMARY, "SELECT pg_current_wal_lsn()"))
    for table in TABLES:
        query = f"SELECT count(*) FROM {table}"
        on_primary, on_replica = scalar(PRIMARY, query), scalar(REPLICA, query)
        # users — глобальна таблиця лише на Shard A (ADR 0054): на Shard B вона порожня на обох вузлах.
        filled = int(on_primary) > 0 if (table != "users" or SHARD == "A") else on_primary == "0"
        check(on_primary == on_replica and filled, f"{table}: primary {on_primary}, replica {on_replica}")


def mutations():
    step("3. Mutations through the API reach the replica")
    status, body = call("POST", "/api/auth/login", body={"email": "user001@example.com", "password": "Password123!"})
    if status != 200:
        check(False, f"login returned {status}")
        return
    token = body["accessToken"]

    def create(title):
        # Шард вибирає роутер за id (лаба 7), тож створюємо, доки опитування не ляже на перевірюваний шард; чужі
        # чернетки одразу видаляємо.
        for _ in range(30):
            code, poll = call("POST", "/api/polls", token, {
                "title": title, "options": ["A", "B"], "endsAt": "2035-01-01T00:00:00Z"})
            if code != 201:
                raise RuntimeError(f"create poll returned {code}")
            if scalar(PRIMARY, f"SELECT count(*) FROM polls WHERE id = {poll['id']}") == "1":
                return poll["id"]
            call("DELETE", f"/api/polls/{poll['id']}", token)
        raise RuntimeError(f"no new poll landed on shard {SHARD}")

    title = f"Replication check {int(time.time())}"
    poll_id = create(title)
    replicated(f"INSERT (poll {poll_id})", f"SELECT title FROM polls WHERE id = {poll_id}", title)

    call("PATCH", f"/api/polls/{poll_id}/publish", token)
    replicated(f"UPDATE (publish poll {poll_id})", f"SELECT status FROM polls WHERE id = {poll_id}", "active")

    doomed = create(f"{title} (to delete)")
    wait_replayed(scalar(PRIMARY, "SELECT pg_current_wal_lsn()"))
    call("DELETE", f"/api/polls/{doomed}", token)
    replicated(f"DELETE (poll {doomed})", f"SELECT count(*) FROM polls WHERE id = {doomed}", "0")


def read_only():
    step("4. The replica rejects writes")
    # WHERE id = -1: якщо вузол раптом приймає запис, запит усе одно не змінить жодного рядка.
    code, _, err = psql(REPLICA, "UPDATE polls SET title = title WHERE id = -1")
    print(f"  UPDATE on the replica: exit code {code}, {err}")
    check(code != 0 and "read-only transaction" in err, "the replica answers with a read-only error")


def main():
    global pause, PRIMARY, REPLICA, SHARD
    parser = argparse.ArgumentParser(description="Lab 6: check primary / replica replication")
    parser.add_argument("--pause", action="store_true", help="wait for Enter before each step")
    parser.add_argument("--shard", choices=sorted(PAIRS), default="A", help="which shard's pair to check (lab 7)")
    args = parser.parse_args()
    pause = args.pause
    SHARD = args.shard
    PRIMARY, REPLICA = PAIRS[SHARD]
    print(f"shard {SHARD}: primary {PRIMARY}, replica {REPLICA}")

    try:
        topology()
        initial_state()
        mutations()
        read_only()
    except (RuntimeError, OSError) as err:
        check(False, f"aborted: {err}")

    print(f"\n{'ALL PASSED' if not failures else f'FAILED: {len(failures)}'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
