#!/usr/bin/env bash
# Перевірка гіпотези H3 окремо від застосунку (лаба 9, ADR 0067): ті самі два оператори каталогу (catalog.sql) на репліці
# Shard A через pgbench у трьох режимах протоколу:
#   simple   — текст запиту щоразу; extended — як Npgsql без підготовки (Parse/Bind/Execute на кожен виклик);
#   prepared — запит підготовлено один раз, далі лише Bind/Execute (так працює Npgsql з Max Auto Prepare).
# Стек має бути піднятий з docker-compose.loadtest-shards.yml (одне ядро на вузол БД) і без іншого навантаження.
#   bash profiling/pgbench/run.sh         # з кореня репозиторію, ≈ 1 хв; результат — profiling/pgbench/results.txt
cd "$(dirname "$0")/../.." || exit 1
export MSYS_NO_PATHCONV=1
out=profiling/pgbench/results.txt
docker compose cp profiling/pgbench/catalog.sql postgres-replica:/tmp/catalog.sql >/dev/null
{
  echo "pgbench on postgres-replica, 20 clients, 4 threads, 15 s per mode, one catalog request on one shard = 2 statements"
  docker compose exec -T postgres-replica sh -c 'nproc; cat /sys/fs/cgroup/cpu.max 2>/dev/null' | tr '\n' ' '
  echo
  for mode in simple extended prepared; do
    echo "== $mode"
    docker compose exec -T postgres-replica pgbench -U polling -d polling -n -f /tmp/catalog.sql -M "$mode" -c 20 -j 4 -T 15 \
      2>&1 | grep -E 'tps|latency average'
  done
} | tee "$out"
