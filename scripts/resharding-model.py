"""Модель решардингу для лаби 7 (пункт 2.5): яка частка даних переїжджає, коли кластер росте з N до M шардів.

Порівнюються п'ять способів на тих самих id 1..K:
  key % N              — наївний modulo;
  hash % N             — хеш fmix64 (як у ShardRouter), але все одно «% N»;
  ring, 1 vnode        — consistent hashing: кожен шард — одна точка на кільці, ключ належить першій точці за годинниковою;
  ring, 100 vnodes     — те саме, але кожен шард має 100 віртуальних вузлів (точок);
  buckets 64           — Virtual Buckets: hash % 64 → таблиця «бакет → шард»; новий шард забирає лише потрібну кількість
                         бакетів у тих, хто має зайві (так змінювалася б таблиця в ShardRouter).
Ідеал — переїжджає лише те, що має опинитися на нових шардах: (M − N) / M.

--live (стек піднятий): ті самі способи на реальних даних обох шардів — скільки рядків (опитування + варіанти + голоси)
довелося б перенести при 2 → 3.

Запуск з кореня репозиторію:  python scripts/resharding-model.py [--keys 100000] [--live]
Лише стандартна бібліотека Python. Вивід англійською — щоб не залежати від кодування консолі.
"""
import argparse
import bisect
import sys

from shardlib import fmix64, psql

BUCKETS = 64
TRANSITIONS = [(2, 3), (3, 4), (2, 4), (4, 5)]


def modulo(n):
    return lambda key: key % n


def hash_mod(n):
    return lambda key: fmix64(key) % n


def ring(n, vnodes):
    """Кільце consistent hashing: точки шардів — хеші пар (шард, номер віртуального вузла)."""
    points = sorted((fmix64(shard * 1_000_003 + v + 1), shard) for shard in range(n) for v in range(vnodes))
    positions = [p for p, _ in points]

    def owner(key):
        i = bisect.bisect_right(positions, fmix64(key))
        return points[i % len(points)][1]
    return owner


def bucket_map(n, previous=None):
    """Таблиця «бакет → шард». Для першої топології — по колу, для наступної — мінімальні зміни попередньої."""
    if previous is None:
        return [b % n for b in range(BUCKETS)]
    table = list(previous)
    target = {s: BUCKETS // n + (1 if s < BUCKETS % n else 0) for s in range(n)}
    owned = {s: [b for b in range(BUCKETS) if table[b] == s] for s in range(n)}
    # Хто має більше за ціль, віддає зайві бакети тим, у кого менше (насамперед новим шардам).
    spare = []
    for s in range(n):
        while len(owned[s]) > target[s]:
            spare.append(owned[s].pop())
    for s in range(n):
        while len(owned[s]) < target[s]:
            b = spare.pop()
            table[b] = s
            owned[s].append(b)
    return table


def buckets(table):
    return lambda key: table[fmix64(key) % BUCKETS]


def methods(n, m):
    """Пари (функція до, функція після) для кожного способу."""
    old_table = bucket_map(n)
    return [
        ("key % N", modulo(n), modulo(m)),
        ("hash % N", hash_mod(n), hash_mod(m)),
        ("ring, 1 vnode", ring(n, 1), ring(m, 1)),
        ("ring, 100 vnodes", ring(n, 100), ring(m, 100)),
        (f"buckets {BUCKETS}", buckets(old_table), buckets(bucket_map(m, old_table))),
    ]


def model(keys):
    print(f"=== Model: ids 1..{keys}, share of keys that move to another shard ===\n")
    header = "method              " + "".join(f"{f'{n} -> {m}':>10}" for n, m in TRANSITIONS)
    print(header)
    rows = {}
    for n, m in TRANSITIONS:
        for name, before, after in methods(n, m):
            moved = sum(1 for k in range(1, keys + 1) if before(k) != after(k))
            rows.setdefault(name, []).append(100 * moved / keys)
    for name, values in rows.items():
        print(f"{name:<19} " + "".join(f"{v:9.1f}%" for v in values))
    print("ideal (M-N)/M       " + "".join(f"{100 * (m - n) / m:9.1f}%" for n, m in TRANSITIONS))

    print(f"\n=== Balance after growing to 3 shards: share of keys per shard (ideal 33.3 % each) ===\n")
    print("method               shard 0  shard 1  shard 2   max / avg")
    for name, _, after in methods(2, 3):
        counts = [0, 0, 0]
        for k in range(1, keys + 1):
            counts[after(k)] += 1
        shares = [100 * c / keys for c in counts]
        print(f"{name:<19} " + "".join(f"{s:8.1f}%" for s in shares) + f"   {max(counts) / (keys / 3):8.2f}")


def live():
    """Реальні опитування з обох шардів: вага опитування = його рядки (сам рядок + варіанти + голоси)."""
    weights = {}
    for shard in ("A", "B"):
        out = psql(shard, "SELECT p.id || ' ' || (1 + (SELECT count(*) FROM options o WHERE o.poll_id = p.id) "
                          "+ (SELECT count(*) FROM votes v WHERE v.poll_id = p.id)) FROM polls p")
        for line in out.splitlines():
            poll_id, rows = line.split()
            weights[int(poll_id)] = int(rows)
    total = sum(weights.values())
    print(f"\n=== Live data: {len(weights)} polls, {total} rows (polls + options + votes) on both shards, 2 -> 3 ===\n")
    print("method              polls moved      rows moved")
    for name, before, after in methods(2, 3):
        moved = [p for p in weights if before(p) != after(p)]
        rows = sum(weights[p] for p in moved)
        print(f"{name:<19} {len(moved):5} = {100 * len(moved) / len(weights):5.1f}%   {rows:6} = {100 * rows / total:5.1f}%")
    print(f"ideal (M-N)/M                 33.3%            33.3%")


def main():
    parser = argparse.ArgumentParser(description="Lab 7: resharding model")
    parser.add_argument("--keys", type=int, default=100_000)
    parser.add_argument("--live", action="store_true", help="also count rows that would move on the running stack")
    args = parser.parse_args()
    model(args.keys)
    if args.live:
        live()


if __name__ == "__main__":
    sys.exit(main())
