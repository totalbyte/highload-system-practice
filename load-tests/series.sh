#!/usr/bin/env bash
# Уся серія вимірювань лаби 5 однією командою (≈ 55 хв). Кожен прогін — на щойно піднятому стеку з чистою БД
# (той самий сід: 500 користувачів, 50 опитувань), інакше прогони впливають один на одного: сценарій C створює
# тисячі опитувань, B — сотні тисяч оновлень гарячих рядків, і наступні прогони міряють уже іншу базу (ADR 0047).
#   bash load-tests/series.sh            # з кореня репозиторію
cd "$(dirname "$0")/.." || exit 1
export MSYS_NO_PATHCONV=1
C="-f docker-compose.yml -f load-tests/docker-compose.loadtest.yml"

state() { curl -s "127.0.0.1:${LB_STATS_PORT:-8404}/stats;csv" | awk -F, -v s="$1" '$1 == "be_api" && $2 == s { print $18 }'; }
wait_state() { for _ in $(seq 1 120); do [[ "$(state "$1")" == $2* ]] && return 0; sleep 1; done; echo "timeout: $1 $2"; }
section() { echo; echo "######## $(date +%H:%M:%S) $*"; }

# fresh <інстансів 1|2|3> [кеш true|false] — чистий стек з потрібною кількістю backend-ів.
fresh() {
  local n=$1 cache=${2:-true}
  docker compose $C --profile scale down -v >/dev/null 2>&1
  RESULTS_CACHE_ENABLED=$cache docker compose $C up -d --build >/dev/null 2>&1
  wait_state backend-1 UP; wait_state backend-2 UP
  if [ "$n" = 1 ]; then docker compose $C stop backend-2 >/dev/null 2>&1; wait_state backend-2 DOWN; fi
  if [ "$n" = 3 ]; then
    RESULTS_CACHE_ENABLED=$cache docker compose $C --profile scale up -d backend-3 >/dev/null 2>&1
    wait_state backend-3 UP
  fi
}

# run <інстансів> <кеш> <сценарій> <мітка> [k6 -e ...]
run() {
  local n=$1 cache=$2 scenario=$3 tag=$4; shift 4
  section "$scenario / $tag ($n instance(s), cache $cache)"
  fresh "$n" "$cache"
  bash load-tests/run.sh "$scenario" "$tag" "$@"
}

run 2 true scenario-a-read baseline
run 2 true scenario-b-write baseline
run 2 true scenario-c-workflow baseline
run 2 true scenario-c-workflow c-extended LEVELS=200,400,800

run 1 true scenario-a-read 1-inst
run 1 true scenario-b-write 1-inst
run 3 true scenario-a-read 3-inst
run 3 true scenario-b-write 3-inst

run 2 false scenario-a-read cache-off

for rate in 300 1200; do
  section "open model for B at $rate req/s"
  fresh 2 true
  docker compose $C run --rm -e RATE=$rate k6 run --quiet open-model.js
done

section "consistency (last stack)"
docker compose exec -T postgres psql -U polling -d polling -tAc \
  "SELECT 'counter mismatches: ' || count(*) FROM options o WHERE o.vote_count <> (SELECT count(*) FROM votes v WHERE v.option_id = o.id)"
section "done"
