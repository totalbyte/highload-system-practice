#!/usr/bin/env bash
# Лаба 8 (ADR 0060): один прогін Cache Stampede з обраним захистом і підрахунком звернень до БД.
#   [RESULTS_LOAD_DELAY_MS=50] bash load-tests/stampede.sh <None|SingleFlight|Lock> [burst|sustained] [-e VUS=500 -e ROUNDS=5 ...]
# RESULTS_LOAD_DELAY_MS — імітація важкого агрегату (pg_sleep у кожному читанні з БД); 0 — справжній агрегат.
# 1) backend-и перезапускаються з RESULTS_STAMPEDE_PROTECTION=<захист>; 2) статистика pg_stat_statements обнуляється
# на Primary обох шардів; 3) k6 (scenario-stampede.js); 4) скільки разів PostgreSQL виконав читання агрегату
# (запит із тегом results-load) — усього і на одну інвалідацію. Стек має бути піднятий; з кореня репозиторію.
cd "$(dirname "$0")/.." || exit 1
export MSYS_NO_PATHCONV=1
protection=${1:?usage: stampede.sh <None|SingleFlight|Lock> [burst|sustained] [k6 -e options]}
mode=${2:-burst}
shift 2 2>/dev/null || shift $#
C="-f docker-compose.yml -f ${OVERLAY:-load-tests/docker-compose.loadtest-lab8.yml}"
delay=${RESULTS_LOAD_DELAY_MS:-0}
# REP — номер повтору в серії (series-lab8.sh): JSON кожного повтору зберігається окремо.
tag=$(echo "$protection" | tr '[:upper:]' '[:lower:]')-delay$delay${REP:+-r$REP}
api=${API:-http://localhost:8080}
poll=1
for arg in "$@"; do case $arg in POLL=*) poll=${arg#POLL=} ;; esac; done

RESULTS_STAMPEDE_PROTECTION=$protection RESULTS_LOAD_DELAY_MS=$delay docker compose $C up -d backend-1 backend-2 \
  >/dev/null 2>&1 || { echo "docker compose up failed"; exit 1; }
for b in backend-1 backend-2; do
  actual=$(docker compose exec -T "$b" sh -c 'echo "$ResultsCache__StampedeProtection $Diagnostics__ResultsLoadDelayMs"' |
    tr -d '\r')
  [ "$actual" = "$protection $delay" ] || { echo "$b runs with '$actual', expected '$protection $delay'"; exit 1; }
done

# Балансувальник має бачити обидва backend-и, інакше прогін ішов би через один інстанс.
seen=""
for _ in $(seq 1 120); do
  id=$(curl -s -o /dev/null -D - "$api/api/polls/$poll/results" | tr -d '\r' | sed -n 's/^X-Instance-ID: //Ip')
  case " $seen " in *" $id "*) ;; *) [ -n "$id" ] && seen="$seen $id" ;; esac
  [ "$(echo $seen | wc -w)" -ge 2 ] && break
  sleep 0.5
done
[ "$(echo $seen | wc -w)" -ge 2 ] || { echo "load balancer does not see both backends (seen:$seen)"; exit 1; }

shards="postgres postgres-shard-b"
psql_q() { docker compose exec -T "$1" psql -U polling -d polling -tAc "$2" | tr -d '\r'; }
for s in $shards; do psql_q "$s" "SELECT pg_stat_statements_reset()" >/dev/null || exit 1; done

docker compose $C run --rm k6 run -q -e MODE="$mode" -e RUN_TAG="$tag" "$@" scenario-stampede.js || exit 1

total=0
for s in $shards; do
  n=$(psql_q "$s" "SELECT coalesce(sum(calls), 0) FROM pg_stat_statements WHERE query LIKE '%results-load%'")
  echo "  $s: $n DB loads of the results aggregate"
  total=$((total + n))
done
# Прогрів (setup і раунд 0 у burst) — не stampede: його звернення віднімаються, k6 рахує їх за X-Cache: MISS.
read -r inv warm < <(python -c "
import json, sys
m = json.load(open(sys.argv[1]))['metrics']
print(m['invalidations']['values']['count'], m.get('warmup_db_loads', {'values': {'count': 0}})['values']['count'])
" "load-tests/results/stampede-$mode-$tag.json" | tr -d '\r')
loads=$((total - warm))
echo "RESULT $protection $mode, load delay $delay ms: $loads DB loads (pg_stat_statements, warm-up $warm excluded) for $inv invalidations =" \
  "$(python -c "print(f'{$loads / max($inv, 1):.1f}')") per invalidation"
# Рядок для звіту серії (series-lab8-report.py); RPS, p95 / p99 і помилки — з JSON k6.
printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$protection" "$mode" "$delay" "${REP:-1}" "$loads" "$inv" \
  "stampede-$mode-$tag.json" >> load-tests/results/stampede-summary.tsv
