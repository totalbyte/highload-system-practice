#!/usr/bin/env bash
# Лаба 8 (ADR 0062): Cache Avalanche — один прогін з обраним розкидом TTL і зняттям навантаження на БД щосекунди.
#   [RESULTS_LOAD_DELAY_MS=50] bash load-tests/avalanche.sh <jitter: 0 | 0.2> [-e VUS=300 -e SECONDS=60 ...]
# Стек — із SEED_POLLS=1000 (≈ 700 активних опитувань = ключів кешу) на оверлеї лаби 8:
#   docker compose down -v && SEED_POLLS=1000 docker compose -f docker-compose.yml -f load-tests/docker-compose.loadtest-lab8.yml up -d --build
# 1) backend-и з RESULTS_TTL_JITTER=<jitter>; 2) кеш результатів порожній, pg_stat_statements обнулено; 3) щосекунди на
# Primary обох шардів: скільки разів читали агрегат і скільки клієнтських сесій активні; 4) k6 scenario-avalanche.js;
# 5) таблиця по секундах — avalanche-report.py. Результати: load-tests/results/avalanche-jitter<j>-delay<d>*.
cd "$(dirname "$0")/.." || exit 1
export MSYS_NO_PATHCONV=1
jitter=${1:?usage: avalanche.sh <jitter 0|0.2> [k6 -e options]}
shift
C="-f docker-compose.yml -f ${OVERLAY:-load-tests/docker-compose.loadtest-lab8.yml}"
delay=${RESULTS_LOAD_DELAY_MS:-0}
tag="jitter${jitter}-delay${delay}"
out="load-tests/results/avalanche-${tag}"
seconds=60
for arg in "$@"; do case $arg in SECONDS=*) seconds=${arg#SECONDS=} ;; esac; done
shards="postgres postgres-shard-b"
psql_q() { docker compose exec -T "$1" psql -U polling -d polling -tAc "$2" | tr -d '\r'; }

polls=0
for s in $shards; do polls=$((polls + $(psql_q "$s" "SELECT count(*) FROM polls"))); done
[ "$polls" -ge 1000 ] || { echo "only $polls polls: start the stack with SEED_POLLS=1000 after down -v (see the header)"; exit 1; }

RESULTS_TTL_JITTER=$jitter RESULTS_LOAD_DELAY_MS=$delay docker compose $C up -d backend-1 backend-2 >/dev/null 2>&1 ||
  { echo "docker compose up failed"; exit 1; }
for b in backend-1 backend-2; do
  actual=$(docker compose exec -T "$b" sh -c 'echo "$ResultsCache__TtlJitter $Diagnostics__ResultsLoadDelayMs"' | tr -d '\r')
  [ "$actual" = "$jitter $delay" ] || { echo "$b runs with '$actual', expected '$jitter $delay'"; exit 1; }
done
for _ in $(seq 1 60); do
  [ "$(curl -s -o /dev/null -w '%{http_code}' localhost:8080/health)" = 200 ] && break; sleep 1
done
sleep 5  # балансувальник має знову бачити обидва backend-и

# Порожній кеш: ключі попереднього прогону спливали б не синхронно з новими.
docker compose exec -T redis sh -c "redis-cli --scan --pattern 'polling:results:v1:*' | xargs -r redis-cli unlink" >/dev/null
for s in $shards; do psql_q "$s" "SELECT pg_stat_statements_reset()" >/dev/null || exit 1; done

# \watch c=N — psql сам завершиться (PostgreSQL 17); setup k6 і старт контейнера займають до ~20 с.
for s in $shards; do
  printf "SELECT extract(epoch FROM now())::bigint,
    (SELECT coalesce(sum(calls), 0) FROM pg_stat_statements WHERE query LIKE '%%results-load%%'),
    (SELECT count(*) FROM pg_stat_activity WHERE backend_type = 'client backend' AND state = 'active' AND pid <> pg_backend_pid())
  \\\\watch i=1 c=%d\n" $((seconds + 40)) |
    docker compose exec -T "$s" psql -U polling -d polling -tA -F $'\t' -q > "${out}-db-${s}.tsv" 2>/dev/null &
done

docker compose $C run --rm k6 run -q -e RUN_TAG="$tag" "$@" scenario-avalanche.js || exit 1
wait
python load-tests/avalanche-report.py "$out.json"
