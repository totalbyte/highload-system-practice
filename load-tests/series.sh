#!/usr/bin/env bash
# Уся серія вимірювань лаби 5 однією командою (≈ 50 хв), з холодного старту — так результати відтворювані.
#   bash load-tests/series.sh            # з кореня репозиторію
# Порядок: baseline A / B / C (2 інстанси, кеш увімкнено) → C до 800 VU → scale 1 / 3 інстанси (A, B) →
# кеш вимкнено (A) → відкрита модель для B (coordinated omission). Результати — load-tests/results/.
cd "$(dirname "$0")/.." || exit 1
export MSYS_NO_PATHCONV=1
C="-f docker-compose.yml -f load-tests/docker-compose.loadtest.yml"

state() { curl -s "127.0.0.1:${LB_STATS_PORT:-8404}/stats;csv" | awk -F, -v s="$1" '$1 == "be_api" && $2 == s { print $18 }'; }
wait_state() { for _ in $(seq 1 120); do [[ "$(state "$1")" == $2* ]] && return 0; sleep 1; done; echo "timeout: $1 $2"; }
section() { echo; echo "######## $(date +%H:%M:%S) $*"; }

section "cold start"
docker compose down -v >/dev/null 2>&1
docker compose $C up -d --build >/dev/null 2>&1
wait_state backend-1 UP; wait_state backend-2 UP

section "baseline: 2 instances, cache on"
for s in scenario-a-read scenario-b-write scenario-c-workflow; do bash load-tests/run.sh "$s" baseline; done

section "scenario C beyond 200 VUs (its saturation point)"
bash load-tests/run.sh scenario-c-workflow c-extended LEVELS=200,400,800

section "scale: 1 instance"
docker compose $C stop backend-2 >/dev/null 2>&1; wait_state backend-2 DOWN
for s in scenario-a-read scenario-b-write; do bash load-tests/run.sh "$s" 1-inst; done

section "scale: 3 instances"
docker compose $C start backend-2 >/dev/null 2>&1; wait_state backend-2 UP
docker compose $C --profile scale up -d backend-3 >/dev/null 2>&1; wait_state backend-3 UP
for s in scenario-a-read scenario-b-write; do bash load-tests/run.sh "$s" 3-inst; done
docker compose $C --profile scale stop backend-3 >/dev/null 2>&1; wait_state backend-3 DOWN

section "cache off (2 instances)"
RESULTS_CACHE_ENABLED=false docker compose $C up -d backend-1 backend-2 >/dev/null 2>&1
sleep 3; wait_state backend-1 UP; wait_state backend-2 UP
bash load-tests/run.sh scenario-a-read cache-off
docker compose $C up -d backend-1 backend-2 >/dev/null 2>&1
sleep 3; wait_state backend-1 UP; wait_state backend-2 UP

section "open model for B: below and above its capacity"
for rate in 500 1500; do docker compose $C run --rm -e RATE=$rate k6 run --quiet open-model.js; done

section "consistency"
docker compose exec -T postgres psql -U polling -d polling -tAc \
  "SELECT 'counter mismatches: ' || count(*) FROM options o WHERE o.vote_count <> (SELECT count(*) FROM votes v WHERE v.option_id = o.id)"
section "done"
