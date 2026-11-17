#!/usr/bin/env bash
# Hot Shard до і після оптимізації стратегії (лаба 7, 2.3, ADR 0056): те саме навантаження scenario-hot-shard на стеку
# з Range (усе нове — на Shard B) і з Buckets. Кожен прогін — на чистому стеку (ADR 0047): стратегію не можна змінити на
# томі з даними. ≈ 4 хв на прогін. З кореня репозиторію:  bash load-tests/hot-shard.sh [LEVELS=10,25,50,100]
# ONLY="range" або ONLY="buckets" — лише один прогін.
cd "$(dirname "$0")/.." || exit 1
set -e
export MSYS_NO_PATHCONV=1
export OVERLAY=load-tests/docker-compose.loadtest-shards.yml
C="-f docker-compose.yml -f $OVERLAY"
levels=${LEVELS:-10,25,50,100}

run() {
  local tag=$1 strategy=$2
  echo "=== $tag: SHARD_STRATEGY=$strategy ==="
  docker compose $C down -v >/dev/null 2>&1
  # Межа 51: сід (id 1..50) — «архів» на Shard A, усі нові опитування — на Shard B.
  SHARD_STRATEGY=$strategy SHARD_RANGE_SIZE=51 docker compose $C up -d --build --wait >/dev/null
  SHARD_STRATEGY=$strategy SHARD_RANGE_SIZE=51 bash load-tests/run.sh scenario-hot-shard "$tag" "LEVELS=$levels" STEP=30
}

for item in ${ONLY:-range buckets}; do
  case $item in
    range) run range Range ;;
    buckets) run buckets Buckets ;;
  esac
done

python load-tests/hot-shard-report.py \
  "Range=load-tests/results/scenario-hot-shard-range-*.json" \
  "Buckets=load-tests/results/scenario-hot-shard-buckets-*.json"

# Повертаємо звичайний стек (стратегія за замовчуванням), щоб наступні перевірки не йшли на Range.
docker compose $C down -v >/dev/null 2>&1
docker compose up -d --wait >/dev/null
