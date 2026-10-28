"""Кеш результатів на двох інстансах: чи бачить backend-2 запис, зроблений через backend-1.

Лаба 2, П2-2 / П2-3. До переносу кешу в Redis (кеш у пам'яті кожного процесу) скрипт показує
застарілі дані на backend-2; після переносу той самий запуск має показати свіжі.

Сценарій A — голос:  прогріти кеш на backend-2 → проголосувати через backend-1 → одразу прочитати з обох.
Сценарій B — publish: автор прогріває кеш чернетки на backend-2 → publish через backend-1 →
                     сторонній читає результати з обох.

Історичне демо лаби 2: йому потрібен прямий доступ до кожного інстансу, а з лаби 3 backend-и не публікують
портів (ADR 0031). Запускати лише з docker-compose.debug.yml, що відкриває порти інстансів для налагодження:
  docker compose -f docker-compose.yml -f docker-compose.debug.yml up -d
  API1=http://127.0.0.1:8091 API2=http://127.0.0.1:8092 python scripts/results-cache-demo.py
Через балансувальник демо втрачає сенс — не видно, хто який інстанс.

Запуск (стек має бути піднятий):  python scripts/results-cache-demo.py
Інші адреси інстансів:            API1=http://host:8080 API2=http://host:8082 python scripts/results-cache-demo.py
Вивід англійською — щоб не залежати від кодування консолі.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

API1 = os.environ.get("API1", "http://localhost:8080")
API2 = os.environ.get("API2", "http://localhost:8082")
PASSWORD = "Password123!"
AUTHOR = "user001@example.com"
VOTER = "user250@example.com"
TTL_SECONDS = 10


def call(base, method, path, token=None, body=None):
    """HTTP-запит; повертає (статус, X-Instance-ID, тіло як dict або None)."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read()
            return resp.status, resp.headers.get("X-Instance-ID"), json.loads(raw) if raw else None
    except urllib.error.HTTPError as err:
        raw = err.read()
        return err.code, err.headers.get("X-Instance-ID"), json.loads(raw) if raw else None


def login(email):
    status, _, body = call(API1, "POST", "/api/auth/login", body={"email": email, "password": PASSWORD})
    if status != 200:
        sys.exit(f"login failed for {email}: HTTP {status}")
    return body["accessToken"]


def create_poll(token, title):
    status, _, body = call(API1, "POST", "/api/polls", token, {
        "title": title,
        "options": ["Yes", "No"],
        "endsAt": "2030-01-01T00:00:00Z",
        "allowVoteChange": False,
    })
    if status != 201:
        sys.exit(f"create poll failed: HTTP {status} {body}")
    return body


def show(step, status, instance, body):
    if status == 200:
        print(f"  {step:<44} {instance:<10} HTTP {status}  totalVotes={body['totalVotes']}"
              f"  status={body['status']}  generatedAt={body['generatedAt']}")
    else:
        print(f"  {step:<44} {instance:<10} HTTP {status}")


def scenario_vote(author, voter):
    print("\nScenario A: vote through backend-1, read through backend-2")
    poll = create_poll(author, f"Cache demo A {int(time.time())}")
    pid = poll["id"]
    _, _, published = call(API1, "PATCH", f"/api/polls/{pid}/publish", author)
    option_id = published["options"][0]["id"]

    show("1. warm cache:     GET results", *call(API2, "GET", f"/api/polls/{pid}/results"))
    status, instance, _ = call(API1, "POST", f"/api/polls/{pid}/vote", voter, {"optionId": option_id})
    print(f"  {'2. vote:           POST vote':<44} {instance:<10} HTTP {status}")
    s2, i2, b2 = call(API2, "GET", f"/api/polls/{pid}/results")
    show("3. right after:    GET results", s2, i2, b2)
    show("   right after:    GET results", *call(API1, "GET", f"/api/polls/{pid}/results"))

    stale = s2 == 200 and b2["totalVotes"] == 0
    if stale:
        print(f"  ... waiting {TTL_SECONDS + 1}s for the TTL ...")
        time.sleep(TTL_SECONDS + 1)
        show("4. after TTL:      GET results", *call(API2, "GET", f"/api/polls/{pid}/results"))
    return stale


def scenario_publish(author):
    print("\nScenario B: publish through backend-1, read through backend-2")
    pid = create_poll(author, f"Cache demo B {int(time.time())}")["id"]

    show("1. author previews draft: GET results", *call(API2, "GET", f"/api/polls/{pid}/results", author))
    status, instance, _ = call(API1, "PATCH", f"/api/polls/{pid}/publish", author)
    print(f"  {'2. publish:        PATCH publish':<44} {instance:<10} HTTP {status}")
    s2, i2, b2 = call(API2, "GET", f"/api/polls/{pid}/results")
    show("3. anonymous:      GET results", s2, i2, b2)
    show("   anonymous:      GET results", *call(API1, "GET", f"/api/polls/{pid}/results"))
    return s2 == 404


def main():
    author, voter = login(AUTHOR), login(VOTER)
    stale_votes = scenario_vote(author, voter)
    stale_access = scenario_publish(author)

    print("\nSummary")
    print(f"  backend-2 served stale vote counts after a vote on backend-1:  {'YES' if stale_votes else 'no'}")
    print(f"  backend-2 answered 404 for a poll published on backend-1:      {'YES' if stale_access else 'no'}")
    if stale_votes or stale_access:
        print("  => the results cache is per-process state: instances disagree until the TTL expires.")
    else:
        print("  => both instances agree immediately: the results cache is shared.")


if __name__ == "__main__":
    main()
