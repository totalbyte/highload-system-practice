#!/usr/bin/env bash
# Лаба 8 (ADR 0063): Cache Penetration — потік запитів до неіснуючих опитувань з негативним кешем і без нього.
#   bash load-tests/penetration.sh <true|false> [-e IDS=100 | -e IDS=0] [-e VUS=200 -e DURATION=30s]
# 1) backend-и з RESULTS_NEGATIVE_CACHING=<true|false>; 2) значення кешу результатів видалено, pg_stat_statements
# обнулено; 3) k6 scenario-penetration.js; 4) скільки разів PostgreSQL шукав агрегат, скільки ключів і пам'яті додалося
# в Redis. Стек піднятий (оверлей лаби 8); з кореня репозиторію.
cd "$(dirname "$0")/.." || exit 1
export MSYS_NO_PATHCONV=1
negative=${1:?usage: penetration.sh <true|false> [k6 -e options]}
shift
C="-f docker-compose.yml -f ${OVERLAY:-load-tests/docker-compose.loadtest-lab8.yml}"
ids=100
for arg in "$@"; do case $arg in IDS=*) ids=${arg#IDS=} ;; esac; done
tag="negative-${negative}-ids${ids}"
shards="postgres postgres-shard-b"
psql_q() { docker compose exec -T "$1" psql -U polling -d polling -tAc "$2" | tr -d '\r'; }
redis_q() { docker compose exec -T redis redis-cli "$@" | tr -d '\r'; }

RESULTS_NEGATIVE_CACHING=$negative docker compose $C up -d backend-1 backend-2 >/dev/null 2>&1 ||
  { echo "docker compose up failed"; exit 1; }
for b in backend-1 backend-2; do
  actual=$(docker compose exec -T "$b" printenv ResultsCache__NegativeCaching | tr -d '\r')
  [ "$actual" = "$negative" ] || { echo "$b runs with '$actual', expected '$negative'"; exit 1; }
done
for _ in $(seq 1 60); do
  [ "$(curl -s -o /dev/null -w '%{http_code}' localhost:8080/health)" = 200 ] && break; sleep 1
done
sleep 5  # балансувальник має знову бачити обидва backend-и

docker compose exec -T redis sh -c "redis-cli --scan --pattern 'polling:results:v1:*' | xargs -r redis-cli unlink" >/dev/null
keys_before=$(redis_q dbsize)
mem_before=$(redis_q info memory | sed -n 's/^used_memory://p')
for s in $shards; do psql_q "$s" "SELECT pg_stat_statements_reset()" >/dev/null || exit 1; done

docker compose $C run --rm k6 run -q -e RUN_TAG="$tag" "$@" scenario-penetration.js || exit 1

loads=0
for s in $shards; do
  loads=$((loads + $(psql_q "$s" "SELECT coalesce(sum(calls), 0) FROM pg_stat_statements WHERE query LIKE '%results-load%'")))
done
keys_after=$(redis_q dbsize)
mem_after=$(redis_q info memory | sed -n 's/^used_memory://p')
requests=$(python -c "import json,sys; print(json.load(open(sys.argv[1]))['requests'])" "load-tests/results/penetration-$tag.json" | tr -d '\r')
echo "RESULT negative caching $negative, ids $ids: $loads DB lookups for $requests requests" \
  "($(python -c "print(f'{100 * $loads / max($requests, 1):.2f}')") %), Redis +$((keys_after - keys_before)) keys," \
  "+$(( (mem_after - mem_before) / 1024 )) KiB"
