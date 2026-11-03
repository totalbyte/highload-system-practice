"""Гонка інвалідації кешу результатів (лаба 4, П1-3, ADR 0041).

Сценарій гонки з лаби 2 (ADR 0026): читач промахнувся і прочитав агрегат з БД ДО коміту голосу; голос закомітився і
інвалідував кеш; читач поклав у кеш свій старий агрегат ПІСЛЯ інвалідації. Далі всі читають застаріле значення до TTL,
хоча виборець уже отримав 201.

Для гонки потрібні щонайменше два голоси поспіль: читач промахується після інвалідації першим, читає БД і кладе
агрегат уже після інвалідації другим. Тому кожен раунд — пачка одночасних голосів нових користувачів за один варіант
(їхні коміти вишиковуються в чергу на блокуванні рядка vote_count, кожен зі своєю інвалідацією), а кілька потоків
весь цей час безперервно читають результати. Коли всі голоси отримали 201, читачі зупиняються, і контрольне читання
має показати рівно стільки голосів, скільки закомічено. Нових голосів до наступного раунду немає, тож застарілий
запис дожив би до TTL — контрольне читання його гарантовано побачить.

Запуск з кореня репозиторію (стек піднятий):  python scripts/cache-race-check.py [--rounds 60] [--burst 8] [--readers 12]
Адреса за замовчуванням — балансувальник, тож читачі й голос розподіляються між інстансами.
Вивід англійською — щоб не залежати від кодування консолі. Код виходу 0 — застарілих читань немає.
"""
import argparse
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

API = os.environ.get("API", "http://localhost:8080")
PASSWORD = "Password123!"


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


def login(email):
    return call("POST", "/api/auth/login", body={"email": email, "password": PASSWORD})[1]["accessToken"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=60)
    parser.add_argument("--burst", type=int, default=8, help="simultaneous votes per round (rounds x burst <= 499 seed users)")
    parser.add_argument("--readers", type=int, default=12, help="parallel readers during each round")
    args = parser.parse_args()
    if args.rounds * args.burst > 499:
        parser.error("rounds x burst must not exceed the 499 seed voters")

    author = login("user001@example.com")
    _, poll = call("POST", "/api/polls", author, {
        "title": f"Cache race {int(time.time() * 1000)}",
        "options": ["Yes", "No"],
        "endsAt": "2030-01-01T00:00:00Z",
    })
    poll_id, option_id = poll["id"], poll["options"][0]["id"]
    call("PATCH", f"/api/polls/{poll_id}/publish", author)

    voter_count = args.rounds * args.burst
    print(f"Logging in {voter_count} voters ...")
    with ThreadPoolExecutor(16) as pool:
        voters = list(pool.map(login, [f"user{i:03d}@example.com" for i in range(2, voter_count + 2)]))

    print(f"Poll {poll_id}: {args.rounds} rounds x {args.burst} simultaneous votes, {args.readers} readers")
    stale_rounds = []
    reads = 0
    for round_no in range(args.rounds):
        stop = threading.Event()
        barrier = threading.Barrier(args.burst)

        def reader():
            n = 0
            while not stop.is_set():
                call("GET", f"/api/polls/{poll_id}/results")
                n += 1
            return n

        def vote(token):
            barrier.wait()
            return call("POST", f"/api/polls/{poll_id}/vote", token, {"optionId": option_id})[0]

        with ThreadPoolExecutor(args.readers) as readers, ThreadPoolExecutor(args.burst) as votes:
            read_futures = [readers.submit(reader) for _ in range(args.readers)]
            statuses = list(votes.map(vote, voters[round_no * args.burst:(round_no + 1) * args.burst]))
            stop.set()
            reads += sum(f.result() for f in read_futures)
        if any(s != 201 for s in statuses):
            print(f"  round {round_no + 1}: votes returned {statuses}")
            return 2

        # Усі читачі вже завершились, нових голосів немає: кеш зараз має відповідати БД.
        expected = (round_no + 1) * args.burst
        _, results = call("GET", f"/api/polls/{poll_id}/results")
        if results["totalVotes"] != expected:
            stale_rounds.append((expected, results["totalVotes"]))

    print(f"  concurrent reads during votes: {reads}")
    print(f"  rounds with a stale read after the vote's 201: {len(stale_rounds)} of {args.rounds}")
    for expected, seen in stale_rounds[:10]:
        print(f"    expected totalVotes={expected}, cache served {seen}")
    print("RESULT:", "no stale reads" if not stale_rounds else "STALE READS FOUND")
    return 0 if not stale_rounds else 1


if __name__ == "__main__":
    sys.exit(main())
