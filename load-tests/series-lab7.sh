#!/usr/bin/env bash
# Лаба 7, 2.6 (ADR 0059): Single Node (SHARD_COUNT=1) проти двох шардів у трьох режимах scenario-shards.js —
# shard-local запис, shard-local читання і fan-out каталогу. Кожен прогін — на чистому стеку (ADR 0047) з тими самими
# лімітами (docker-compose.loadtest-shards.yml: одне ядро на кожен вузол БД). ≈ 4 хв на прогін, 6 прогонів ≈ 25 хв.
#   bash load-tests/series-lab7.sh                 # з кореня репозиторію
#   ONLY="single-read sharded-read" LEVELS=10,50 STEP=20 bash load-tests/series-lab7.sh
cd "$(dirname "$0")/.." || exit 1
set -e
export MSYS_NO_PATHCONV=1
export OVERLAY=load-tests/docker-compose.loadtest-shards.yml
C="-f docker-compose.yml -f $OVERLAY"
levels=${LEVELS:-10,25,50,100,200}
step=${STEP:-30}

run() {
  local topology=$1 mode=$2 count=1
  [ "$topology" = sharded ] && count=2
  echo "=== $topology-$mode: SHARD_COUNT=$count, MODE=$mode ==="
  docker compose $C down -v >/dev/null 2>&1
  SHARD_COUNT=$count docker compose $C up -d --build --wait >/dev/null
  SHARD_COUNT=$count bash load-tests/run.sh "scenario-shards" "$topology-$mode" "MODE=$mode" "LEVELS=$levels" "STEP=$step"
}

all="single-write sharded-write single-read sharded-read single-catalog sharded-catalog"
for item in ${ONLY:-$all}; do
  run "${item%%-*}" "${item#*-}"
done

python load-tests/shards-report.py

# Повертаємо звичайний стек (два шарди, без лімітів).
docker compose $C down -v >/dev/null 2>&1
docker compose up -d --wait >/dev/null
