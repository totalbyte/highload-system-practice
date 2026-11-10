"""Той самий Shard Router, що й у backend (src/PollingPlatform.Api/Sharding/ShardRouter.cs), для скриптів лаби 7.

Скрипт за id сам обчислює очікуваний шард і порівнює з тим, куди насправді пішов запит (X-Shard) і де лежить рядок.
Якщо змінити функцію тут або в C#, перевірки впадуть — це навмисно.
"""
import subprocess

MASK = (1 << 64) - 1
SERVICES = {"A": "postgres", "B": "postgres-shard-b"}


def fmix64(key):
    """Фіналізатор MurmurHash3: сусідні id дають зовсім різні хеші."""
    k = key & MASK
    k ^= k >> 33
    k = (k * 0xFF51AFD7ED558CCD) & MASK
    k ^= k >> 33
    k = (k * 0xC4CEB9FE1A85EC53) & MASK
    k ^= k >> 33
    return k


def shard_for(poll_id, strategy="Buckets", count=2, range_size=1000, buckets=64):
    """Номер шарду: 0 — A, 1 — B. Бакети розкладені по шардах по колу, як у ShardRouter."""
    if count == 1:
        return 0
    strategy = strategy.lower()
    if strategy == "range":
        return min(poll_id // range_size, count - 1)
    if strategy == "modulo":
        return poll_id % count
    if strategy == "hash":
        return fmix64(poll_id) % count
    return (fmix64(poll_id) % buckets) % count


def name(shard):
    return chr(ord("A") + shard)


def backend_config():
    """Налаштування шардингу живого backend-1: скрипт перевіряє ту стратегію, з якою стек справді піднято."""
    def env(key, default):
        done = subprocess.run(["docker", "compose", "exec", "-T", "backend-1", "printenv", key],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        return done.stdout.strip() or default
    return {
        "strategy": env("Sharding__Strategy", "Buckets"),
        "count": int(env("Sharding__ShardCount", "2")),
        "range_size": int(env("Sharding__RangeSize", "1000")),
        "buckets": int(env("Sharding__Buckets", "64")),
    }


def psql(shard_name, query):
    """Запит прямо в Primary шарду, повз застосунок: незалежна перевірка, де лежать дані."""
    done = subprocess.run(
        ["docker", "compose", "exec", "-T", SERVICES[shard_name], "psql", "-U", "polling", "-d", "polling", "-tAc", query],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)
    return done.stdout.strip()
