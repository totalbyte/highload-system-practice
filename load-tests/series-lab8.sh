#!/usr/bin/env bash
# Лаба 8, 2.7 (ADR 0064): уся серія для порівняльної матриці на одному стенді, ≈ 35 хв.
#   bash load-tests/series-lab8.sh            # з кореня репозиторію; стек буде перестворено (down -v)
# Повтори йдуть «по колу» (повтор 1 усіх режимів, потім повтор 2…), щоб дрейф машини розподілився між режимами.
#   1) stampede sustained 30 с, 500 VU, інвалідація кожні 200 мс: None / SingleFlight / Lock × агрегат + 50 мс і справжній × 3;
#   2) stampede burst (500 VU одночасно, 5 інвалідацій): None / SingleFlight / Lock, агрегат + 50 мс, × 1 — кількість
#      звернень до БД тут детермінована;
#   3) penetration 30 с, 200 VU, 100 неіснуючих id: None + без негативного кешу (зовсім незахищений «до»),
#      Lock + без нього, Lock + з ним × 3;
#   4) контроль: сценарій A лаби 5 (50 і 200 VU) з поведінкою до лаби 8 (SingleFlight, без негативного кешу) і з
#      поведінкою лаби 8 (Lock + негативний кеш) × 2 — чи не сповільнилось звичайне читання.
# Наприкінці стек повертається до звичайного (без оверлею), звіт — series-lab8-report.py.
cd "$(dirname "$0")/.." || exit 1
export MSYS_NO_PATHCONV=1
C="-f docker-compose.yml -f load-tests/docker-compose.loadtest-lab8.yml"
R=load-tests/results
mkdir -p $R
set -o pipefail

docker compose down -v >/dev/null 2>&1
docker compose $C up -d --build >/dev/null 2>&1 || { echo "stack failed to start"; exit 1; }
for _ in $(seq 1 90); do [ "$(curl -s -o /dev/null -w '%{http_code}' localhost:8080/health)" = 200 ] && break; sleep 2; done
rm -f $R/stampede-summary.tsv $R/penetration-summary.tsv $R/scenario-a-read-lab8-*.json
started=$(date +%s)
step() { echo "[$(( ($(date +%s) - started) / 60 )) min] $*"; }

for rep in 1 2 3; do
  for delay in 50 0; do
    for p in None SingleFlight Lock; do
      step "stampede sustained $p delay $delay rep $rep"
      REP=$rep RESULTS_LOAD_DELAY_MS=$delay bash load-tests/stampede.sh $p sustained | grep '^RESULT' || exit 1
    done
  done
done

for p in None SingleFlight Lock; do
  step "stampede burst $p delay 50"
  REP=1 RESULTS_LOAD_DELAY_MS=50 bash load-tests/stampede.sh $p burst | grep '^RESULT' || exit 1
done

for rep in 1 2 3; do
  for cfg in "None false" "Lock false" "Lock true"; do
    set -- $cfg
    step "penetration $1 negative $2 rep $rep"
    REP=$rep RESULTS_STAMPEDE_PROTECTION=$1 bash load-tests/penetration.sh $2 | grep '^RESULT' || exit 1
  done
done

for rep in 1 2; do
  for cfg in "SingleFlight false" "Lock true"; do
    set -- $cfg
    step "scenario A $1 negative $2 rep $rep"
    RESULTS_STAMPEDE_PROTECTION=$1 RESULTS_NEGATIVE_CACHING=$2 docker compose $C up -d backend-1 backend-2 >/dev/null 2>&1
    for _ in $(seq 1 60); do [ "$(curl -s -o /dev/null -w '%{http_code}' localhost:8080/health)" = 200 ] && break; sleep 1; done
    sleep 5
    docker compose $C run --rm k6 run -q -e LEVELS=50,200 -e STEP=30 -e WARMUP=10 \
      -e RUN_TAG="lab8-$(echo "$1" | tr '[:upper:]' '[:lower:]')-r$rep" scenario-a-read.js >/dev/null 2>&1 || exit 1
  done
done

step "done, restoring the default stack"
docker compose up -d >/dev/null 2>&1
python load-tests/series-lab8-report.py
