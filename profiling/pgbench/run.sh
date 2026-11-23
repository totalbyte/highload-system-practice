#!/usr/bin/env bash
# Перевірка гіпотези H3 окремо від застосунку (лаба 9, ADR 0067): ті самі два оператори каталогу (catalog.sql) на репліці
# кожного шарду через pgbench у трьох режимах протоколу:
#   simple   — текст запиту щоразу; extended — як Npgsql без підготовки (Parse/Bind/Execute на кожен виклик);
#   prepared — запит підготовлено один раз, далі лише Bind/Execute (так працює Npgsql з Max Auto Prepare).
# Кожен режим — REPEATS разів через один (simple, extended, prepared, simple, ...), щоб дрейф машини ділився порівну;
# у звіті медіана і розкид min–max. Перед стартом чекає, поки репліки відтворять увесь WAL: у першій версії прогін
# одразу після перестворення стеку дав у 5 разів менші числа, ніж такий самий на спокійному стеку.
# Стек має бути піднятий з docker-compose.loadtest-shards.yml (одне ядро на вузол БД) і без іншого навантаження.
#   bash profiling/pgbench/run.sh         # з кореня репозиторію, ≈ 5 хв; результат — profiling/pgbench/results.txt
cd "$(dirname "$0")/../.." || exit 1
export MSYS_NO_PATHCONV=1
out=profiling/pgbench/results.txt
repeats=${REPEATS:-3}
declare -A primary=([postgres-replica]=postgres [postgres-shard-b-replica]=postgres-shard-b)

for replica in postgres-replica postgres-shard-b-replica; do
  docker compose cp profiling/pgbench/catalog.sql "$replica:/tmp/catalog.sql" >/dev/null
  # Репліка наздогнала Primary: позиція відтворення дорівнює поточній позиції WAL на Primary.
  for i in $(seq 1 60); do
    lsn=$(docker compose exec -T "${primary[$replica]}" psql -U polling -d polling -tAc "SELECT pg_current_wal_lsn()")
    caught=$(docker compose exec -T "$replica" psql -U polling -d polling -tAc "SELECT pg_last_wal_replay_lsn() >= '$lsn'")
    [ "$caught" = t ] && break
    sleep 1
  done
done

{
  echo "pgbench, 20 clients, 4 threads, 15 s per run, $repeats runs per mode interleaved; one catalog request on one shard = 2 statements"
  for replica in postgres-replica postgres-shard-b-replica; do
    echo
    echo "== $replica: cpu.max $(docker compose exec -T "$replica" cat /sys/fs/cgroup/cpu.max | tr -d '\r'), $(docker compose exec -T "$replica" psql -U polling -d polling -tAc "SELECT count(*) FROM polls WHERE is_public AND status = 'active'") active public polls"
    declare -A runs=()
    for r in $(seq 1 "$repeats"); do
      for mode in simple extended prepared; do
        tps=$(docker compose exec -T "$replica" pgbench -U polling -d polling -n -f /tmp/catalog.sql -M "$mode" -c 20 -j 4 -T 15 2>&1 \
          | awk '/^tps/ {printf "%.0f", $3}')
        runs[$mode]="${runs[$mode]} $tps"
      done
    done
    for mode in simple extended prepared; do
      echo "$mode:${runs[$mode]}" | awk '{n=split($0,a," "); m=""; for(i=2;i<=n;i++) v[i-1]=a[i]; c=n-1;
        for(i=1;i<=c;i++) for(j=i+1;j<=c;j++) if (v[j]<v[i]) {t=v[i]; v[i]=v[j]; v[j]=t}
        printf "%-9s tps median %6d   min %6d   max %6d   runs:%s\n", a[1], v[int((c+1)/2)], v[1], v[c], substr($0, index($0,":")+1)}'
    done
    unset runs
  done
} | tee "$out"
