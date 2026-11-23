#!/usr/bin/env bash
# A/B лаби 9 (пункт 2.4, ADR 0069): каталог до (DB_MAX_AUTO_PREPARE=0) і після (20) оптимізації в тотожних умовах —
# той самий стенд, що й у лабі 7 (docker-compose.loadtest-shards.yml: одне ядро на вузол БД), чистий стек на кожен прогін,
# конфігурації чергуються (before, after, before, after...), щоб дрейф машини ділився між ними порівну.
# Регресія: по одному прогону запису голосів і читання деталей для кожної конфігурації — інші частини системи.
#   bash profiling/ab-series.sh                       # ≈ 40 хв; з кореня репозиторію
#   REPEATS=1 LEVELS=10,50 STEP=20 ONLY_CATALOG=1 bash profiling/ab-series.sh
# Звіт: python profiling/ab-report.py → profiling/ab-report.md
cd "$(dirname "$0")/.." || exit 1
set -e
export MSYS_NO_PATHCONV=1
export OVERLAY=load-tests/docker-compose.loadtest-shards.yml
C="-f docker-compose.yml -f $OVERLAY"
levels=${LEVELS:-10,25,50,100,200}
step=${STEP:-30}
repeats=${REPEATS:-3}

wait_login() {
  # HAProxy повертає backend у пул пізніше, ніж compose вважає його здоровим: без цього setup k6 отримує 503.
  for i in $(seq 1 60); do
    code=$(curl -s -o load-tests/results/.login -w '%{http_code}' -X POST localhost:8080/api/auth/login \
      -H 'Content-Type: application/json' -d '{"email":"user001@example.com","password":"Password123!"}' || true)
    [ "$code" = 200 ] && return 0
    sleep 1
  done
  echo "login still returns $code"; return 1
}

run() {
  local config=$1 prepare=$2 mode=$3 tag=$4
  echo "=== $tag: DB_MAX_AUTO_PREPARE=$prepare, MODE=$mode"
  docker compose $C down -v >/dev/null 2>&1
  DB_MAX_AUTO_PREPARE=$prepare docker compose $C up -d --build --wait >/dev/null 2>&1
  wait_login
  DB_MAX_AUTO_PREPARE=$prepare bash load-tests/run.sh scenario-shards "$tag" "MODE=$mode" "LEVELS=$levels" "STEP=$step" \
    | grep -E '^(warmup|vus_)'
}

mkdir -p load-tests/results
for r in $(seq 1 "$repeats"); do
  run before 0 catalog "ab-before-catalog-$r"
  run after 20 catalog "ab-after-catalog-$r"
done
if [ "${ONLY_CATALOG:-0}" != 1 ]; then
  for mode in write read; do
    run before 0 "$mode" "ab-before-$mode-1"
    run after 20 "$mode" "ab-after-$mode-1"
  done
fi
rm -f load-tests/results/.login

# Сирі результати — у репозиторій (load-tests/results/ у .gitignore): зведення k6 кожного прогону, заміри ресурсів, середовище.
mkdir -p profiling/ab-results
cp load-tests/results/scenario-shards-*-ab-*.json load-tests/results/scenario-shards-ab-*-resources.tsv   load-tests/results/scenario-shards-ab-*-env.txt profiling/ab-results/

python profiling/ab-report.py

# Назад до звичайного стеку (оптимізацію ввімкнено за замовчуванням).
docker compose $C down -v >/dev/null 2>&1
docker compose up -d --wait >/dev/null 2>&1
