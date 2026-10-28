"""Відмова вузла під потоком читання через балансувальник (лаба 3, П1-3, пункти 2.4.2–2.4.3 методички).

Кілька потоків безперервно шлють GET через балансувальник. Через --fail-at секунд вузол зупиняється
(`docker compose stop` або `kill`), через --start-at — запускається знову. Паралельно скрипт читає сторінку
статистики HAProxy і фіксує, коли балансувальник виключив вузол і коли повернув його в пул.
Очікування: жодного 5xx і жодного обриву з'єднання у клієнта; вузол повертається сам, без перезапуску `lb`.
Відмова під час запису (голосування) — kill-test.py Учасника 2 (П2-4).

Запуск з кореня репозиторію (стек піднятий, обидва вузли UP):
  python scripts/lb-failover.py              # stop backend-2
  python scripts/lb-failover.py --kill       # kill backend-2 (SIGKILL — обриває запити на льоту)
127.0.0.1, а не localhost — див. kill-test.py. Стандартна бібліотека. Вузол запускається знову навіть при помилці.
"""
import argparse
import collections
import csv
import http.client
import io
import subprocess
import threading
import time
import urllib.request

LB = ("127.0.0.1", 8080)
STATS = "http://127.0.0.1:8404/stats;csv"
PATH = "/api/polls?pageSize=5"


def server_status(node):
    with urllib.request.urlopen(STATS, timeout=2) as r:
        for row in csv.DictReader(io.StringIO(r.read().decode().lstrip("# "))):
            if row["pxname"] == "be_api" and row["svname"] == node:
                return row["status"]
    return "?"


def main():
    parser = argparse.ArgumentParser(description="Node failure under a read stream through the load balancer")
    parser.add_argument("--node", default="backend-2")
    parser.add_argument("--kill", action="store_true", help="docker compose kill instead of stop")
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--fail-at", type=float, default=3)
    parser.add_argument("--start-at", type=float, default=10)
    parser.add_argument("--duration", type=float, default=22)
    args = parser.parse_args()
    action = "kill" if args.kill else "stop"

    t0 = time.monotonic()
    now = lambda: time.monotonic() - t0
    done = threading.Event()
    lock = threading.Lock()
    events = []                                  # (час, подія)
    log = []                                     # (час, код або назва помилки, інстанс, затримка)

    def worker():
        conn = None
        while not done.is_set():
            started = time.monotonic()
            try:
                if conn is None:
                    conn = http.client.HTTPConnection(*LB, timeout=30)
                conn.request("GET", PATH)
                r = conn.getresponse()
                r.read()
                result, instance = r.status, r.getheader("X-Instance-ID")
            except Exception as e:  # обрив з'єднання з балансувальником — теж відмова для клієнта
                result, instance = type(e).__name__, None
                conn = None
            with lock:
                log.append((now(), result, instance, time.monotonic() - started))

    def watch():
        last = None
        while not done.is_set():
            try:
                status = server_status(args.node)
            except Exception as e:
                status = type(e).__name__
            if status != last:
                events.append((now(), f"HAProxy: {args.node} {status}"))
                last = status
            time.sleep(0.1)

    threads = [threading.Thread(target=worker) for _ in range(args.threads)] + [threading.Thread(target=watch)]
    for t in threads:
        t.start()
    try:
        while now() < args.fail_at:
            time.sleep(0.05)
        events.append((now(), f"docker compose {action} {args.node}"))
        subprocess.run(["docker", "compose", action, args.node], capture_output=True)
        events.append((now(), f"  ... {action} returned"))
        while now() < args.start_at:
            time.sleep(0.05)
    finally:
        events.append((now(), f"docker compose start {args.node}"))
        subprocess.run(["docker", "compose", "start", args.node], capture_output=True)
    while now() < args.duration:
        time.sleep(0.05)
    done.set()
    for t in threads:
        t.join()

    print(f"{args.threads} threads x GET {PATH} through the balancer, {args.duration:.0f}s; "
          f"{action} {args.node} at {args.fail_at:.0f}s, start at {args.start_at:.0f}s")
    for at, what in sorted(events):
        print(f"  {at:6.2f}s  {what}")

    first_back = next((at for at, _, inst, _ in log if inst == args.node and at > args.start_at), None)
    phases = [("before", 0, args.fail_at), ("node down", args.fail_at, args.start_at), ("after start", args.start_at, args.duration)]
    print(f"\n{'phase':<12}{'requests':>9}  {'by instance':<34}{'non-2xx / errors':<20}{'max latency':>11}")
    for name, lo, hi in phases:
        part = [x for x in log if lo <= x[0] < hi]
        by = collections.Counter(inst for _, _, inst, _ in part if inst)
        bad = collections.Counter(res for _, res, _, _ in part if not (isinstance(res, int) and res < 300))
        slow = max((lat for *_, lat in part), default=0)
        print(f"{name:<12}{len(part):>9}  {', '.join(f'{k} {v}' for k, v in sorted(by.items())):<34}"
              f"{str(dict(bad)) if bad else '0':<20}{slow * 1000:>9.0f}ms")
    total_bad = sum(1 for _, res, _, _ in log if not (isinstance(res, int) and res < 300))
    print(f"\nclient saw {total_bad} non-2xx responses / connection errors out of {len(log)} requests")
    if first_back is not None:
        print(f"first response from {args.node} after start: +{first_back - args.start_at:.2f}s")
    else:
        print(f"{args.node} did not serve any request after start")


if __name__ == "__main__":
    main()
