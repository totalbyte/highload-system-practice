#!/usr/bin/env bash
# Серія вимірювань лаби 6 (2.6): Single Primary проти Primary + Replica, 17 прогонів, ≈ 95 хв. Кожен прогін — на чистому стеку (ADR 0047),
# конфігурації чергуються, щоб дрейф машини (нагрів, фонові процеси) не працював проти однієї з них.
#   bash load-tests/series-lab6.sh                                  # з кореня репозиторію, уся серія
#   ONLY="single-mixed-1 replica-mixed-1" bash load-tests/series-lab6.sh     # лише вибрані прогони (за міткою)
#   LEVELS=10,50 STEP=10 WARMUP=5 MIXED_STEP=70 ONLY=... bash load-tests/series-lab6.sh   # короткий сухий прогін
# Single Primary — репліку справді зупинено: у вимірах немає ні її читань, ні передачі WAL.
cd "$(dirname "$0")/.." || exit 1
set -eo pipefail
export MSYS_NO_PATHCONV=1
export OVERLAY=${OVERLAY:-load-tests/docker-compose.loadtest-8cpu.yml}
C="-f docker-compose.yml -f $OVERLAY"
EXTRA=()
for v in LEVELS STEP WARMUP; do [ -n "${!v:-}" ] && EXTRA+=("$v=${!v}"); done
WRITERS=${WRITERS:-15}

state() { curl -s "127.0.0.1:${LB_STATS_PORT:-8404}/stats;csv" | awk -F, -v s="$1" '$1 == "be_api" && $2 == s { print $18 }'; }
wait_up() {
  for _ in $(seq 1 120); do [[ "$(state "$1")" == UP* ]] && return 0; sleep 1; done
  echo "timeout: $1 is not UP in HAProxy" >&2
  return 1
}
# Стан UP у статистиці недостатній: HAProxy показує його одразу після резолву DNS, ще до першої перевірки, коли backend
# навіть не слухає порт. Готовність — справжні відповіді API від обох інстансів.
wait_ready() {
  for _ in $(seq 1 120); do
    seen=$(for _ in 1 2 3 4 5 6; do
      curl -si "127.0.0.1:${LB_PORT:-8080}/api/polls?pageSize=1" | tr -d '\r' | awk 'NR == 1 && $2 != 200 { exit } tolower($1) == "x-instance-id:" { print $2 }'
    done | sort -u | wc -l)
    [ "$seen" -ge 2 ] && return 0
    sleep 1
  done
  echo "timeout: the API did not answer from both instances" >&2
  return 1
}
section() { echo; echo "######## $(date +%H:%M:%S) $*"; }
selected() { [ -z "${ONLY:-}" ] || [[ " $ONLY " == *" $1 "* ]]; }
node() { curl -si "127.0.0.1:${LB_PORT:-8080}/api/polls?pageSize=1" | tr -d '\r' | awk 'tolower($1) == "x-db-node:" { print $2 }'; }

# fresh <single|replica> <кеш true|false> — чистий стек; перевіряє, що читання справді йдуть на очікуваний вузол.
fresh() {
  local topology=$1 cache=$2 replica=true expected=replica
  [ "$topology" = single ] && { replica=false; expected=primary; }
  docker compose $C --profile scale down -v >/dev/null 2>&1
  READ_REPLICA_ENABLED=$replica RESULTS_CACHE_ENABLED=$cache docker compose $C up -d --build >/dev/null 2>&1
  wait_up backend-1; wait_up backend-2; wait_ready
  if [ "$topology" = single ]; then
    docker compose $C stop postgres-replica >/dev/null 2>&1
    # Слот зупиненої репліки тримав би WAL: сегменти не перевикористовуються, а створюються заново, і запис сповільнюється.
    # Справжній Single Primary слота не має, інакше порівняння міряло б не топологію, а цей артефакт (ADR 0053).
    docker compose exec -T postgres psql -U polling -d polling -qtAc "SELECT pg_drop_replication_slot('replica_1')" >/dev/null
  else
    for _ in $(seq 1 60); do
      [ "$(docker compose exec -T postgres psql -U polling -d polling -tAc "SELECT count(*) FROM pg_stat_replication WHERE state = 'streaming'" | tr -d '\r')" = 1 ] && break
      sleep 1
    done
  fi
  sleep 5
  local actual; actual=$(node)
  [ "$actual" = "$expected" ] || { echo "wrong stand: X-DB-Node=$actual, expected $expected" >&2; return 1; }
}

# run <single|replica> <кеш> <сценарій> <мітка>
run() {
  local topology=$1 cache=$2 scenario=$3 tag=$4
  selected "$tag" || return 0
  section "$scenario / $tag ($topology, cache $cache)"
  fresh "$topology" "$cache"
  bash load-tests/run.sh "$scenario" "$tag" "${EXTRA[@]}"
}

# mixed <single|replica> <мітка> — сценарій A вимірюється, поки WRITERS VU сценарію B постійно голосують. Кеш увімкнено, як у
# робочій системі. Те, чого не показує чисте читання: чи заважає запис читанню, коли вони на одному вузлі.
mixed() {
  local topology=$1 tag=$2
  selected "$tag" || return 0
  section "mixed: scenario A with $WRITERS writers / $tag ($topology)"
  fresh "$topology" true
  docker compose $C run --rm -e RUN_TAG="$tag-writers" -e LEVELS="$WRITERS" -e STEP="${MIXED_STEP:-330}" -e WARMUP=5 \
    k6 run --quiet scenario-b-write.js > "load-tests/results/$tag-writers.log" 2>&1 &
  local writers=$!
  # Логін 500 користувачів у setup() сценарію B навантажує backend-и; читачі стартують, коли він завершився.
  sleep "${MIXED_DELAY:-60}"
  bash load-tests/run.sh scenario-a-read "$tag" "${EXTRA[@]}"
  wait "$writers"
}

check_counters() {
  # Лаба 7: лічильники на кожному шарді.
  for db in postgres postgres-shard-b; do
    docker compose exec -T $db psql -U polling -d polling -tAc \
      "SELECT '$db counter mismatches: ' || count(*) FROM options o WHERE o.vote_count <> (SELECT count(*) FROM votes v WHERE v.option_id = o.id)"
  done
}

run single  true  scenario-a-read     single-a-on
run replica true  scenario-a-read     replica-a-on
run replica false scenario-a-read     replica-a-off-1
run single  false scenario-a-read     single-a-off-1
run single  false scenario-a-read     single-a-off-2
run replica false scenario-a-read     replica-a-off-2
mixed single  single-mixed-1;  selected single-mixed-1 && check_counters
mixed replica replica-mixed-1; selected replica-mixed-1 && check_counters
mixed replica replica-mixed-2; selected replica-mixed-2 && check_counters
mixed single  single-mixed-2;  selected single-mixed-2 && check_counters
mixed replica replica-mixed-3; selected replica-mixed-3 && check_counters
run single  true  scenario-b-write    single-b-1; selected single-b-1 && check_counters
run replica true  scenario-b-write    replica-b-1; selected replica-b-1 && check_counters
run replica true  scenario-b-write    replica-b-2; selected replica-b-2 && check_counters
run single  true  scenario-b-write    single-b-2; selected single-b-2 && check_counters
run replica true  scenario-b-write    replica-b-3; selected replica-b-3 && check_counters
run replica true  scenario-c-workflow replica-c; selected replica-c && check_counters
run single  true  scenario-c-workflow single-c; selected single-c && check_counters
section "done"
