#!/usr/bin/env bash
# Збір доказів лаби 9 (ADR 0067) під тим самим навантаженням: каталог (scenario-shards.js, MODE=catalog) на двох шардах,
# одне ядро на кожен вузол БД (docker-compose.loadtest-shards.yml). Поки йде навантаження, знімаються:
#   - лічильники .NET (CPU, GC, алокації, пул потоків) і пулу Npgsql — dotnet-counters, 30 с;
#   - профіль часу потоків backend-1 — dotnet-trace, 15 с → flame graph (лише CPU_TIME) і топ функцій;
#   - два знімки купи — dotnet-gcdump на початку і в кінці (чи росте купа = витік);
#   - CPU / пам'ять контейнерів кожні 5 с; очікування сесій PostgreSQL;
# після навантаження — pg_stat_statements обох реплік (планування окремо від виконання) і EXPLAIN ANALYZE запитів каталогу.
#   bash profiling/collect.sh baseline        # з кореня репозиторію; стек піднімається сам, на чистих томах
#   VUS=50 DUR=100 FRESH_STACK=0 bash profiling/collect.sh optimized
# Результат — profiling/<мітка>/; великі сирі файли (.nettrace, .speedscope.json) — у .gitignore.
cd "$(dirname "$0")/.." || exit 1
set -e
export MSYS_NO_PATHCONV=1
label=${1:?usage: collect.sh <label>}
vus=${VUS:-50}
dur=${DUR:-100}
C="-f docker-compose.yml -f load-tests/docker-compose.loadtest-shards.yml"
out=profiling/$label
mkdir -p "$out"
psql() { docker compose exec -T "$1" psql -U polling -d polling "${@:2}"; }

if [ "${FRESH_STACK:-1}" = 1 ]; then
  echo "== fresh stack"
  docker compose $C down -v >/dev/null 2>&1
  docker compose $C up -d --build --wait >/dev/null
fi
docker compose exec -T backend-1 sh -c 'rm -f /tmp/*.nettrace /tmp/*.gcdump /tmp/*.csv /tmp/*.json'
# `up --wait` чекає healthcheck контейнерів, але HAProxy повертає backend у пул лише після кількох своїх перевірок:
# без цього очікування setup k6 отримував 503 на логіні, і «навантаження» було порожнім.
for i in $(seq 1 60); do
  code=$(curl -s -o "$out/.login" -w '%{http_code}' -X POST localhost:8080/api/auth/login -H 'Content-Type: application/json'     -d '{"email":"user001@example.com","password":"Password123!"}')
  [ "$code" = 200 ] && break
  sleep 1
done
[ "$code" = 200 ] || { echo "login still returns $code"; exit 1; }
rm -f "$out/.login"   # тіло відповіді: /dev/null не годиться, бо MSYS_NO_PATHCONV=1 лишає шлях Windows-curl як є

echo "== load: catalog, $vus VUs, ${dur}s (k6 log: $out/k6.txt)"
docker compose $C run --rm -T -e MODE=catalog -e LEVELS="$vus" -e STEP="$dur" -e WARMUP=10 -e FRESH=5 \
  -e RUN_TAG="prof-$label" k6 run --quiet scenario-shards.js > "$out/k6.txt" 2>&1 &
k6=$!
sleep 30   # логін 200 користувачів, розігрів 10 с і пауза 5 с — далі рівне навантаження

for db in postgres-replica postgres-shard-b-replica; do
  psql $db -qtAc "SELECT pg_stat_statements_reset()" >/dev/null
  psql $db -qtAc "SELECT pg_stat_reset()" >/dev/null
done
started=$(date +%s)

( printf 'epoch_s\tcontainer\tcpu_pct\tmem\n'
  for i in $(seq 1 12); do
    t=$(date +%s)
    docker stats --no-stream --format '{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}' |
      grep -E 'backend|postgres|lb-1|redis' | sed "s/^polling-platform-//; s/-1\t/\t/; s/^/${t}\t/"
    sleep 4
  done ) > "$out/docker-stats.tsv" &
stats=$!

( printf 'epoch_s\tstate\twait_event_type\twait_event\tsessions\n'
  for i in $(seq 1 10); do
    psql postgres-replica -tA -F $'\t' -c "SELECT extract(epoch FROM now())::int, coalesce(state, '-'), coalesce(wait_event_type, 'CPU'),
      coalesce(wait_event, '-'), count(*) FROM pg_stat_activity WHERE backend_type = 'client backend' AND pid <> pg_backend_pid()
      GROUP BY 1, 2, 3, 4 ORDER BY 5 DESC"
    sleep 5
  done ) > "$out/pg-activity-replica-a.tsv" 2>&1 &
activity=$!

echo "== gcdump #1"
docker compose exec -T backend-1 sh -c 'cd /tmp && dotnet-gcdump collect -p 1 -o /tmp/heap-1.gcdump >/dev/null'
echo "== dotnet-counters, 30 s"
docker compose exec -T backend-1 sh -c 'cd /tmp && dotnet-counters collect -p 1 --duration 00:00:30 --format csv -o /tmp/counters.csv \
  --counters System.Runtime,Npgsql,Microsoft.AspNetCore.Hosting,Microsoft.AspNetCore.Server.Kestrel >/dev/null'
echo "== dotnet-trace, 15 s"
docker compose exec -T backend-1 sh -c 'cd /tmp && dotnet-trace collect -p 1 --profile dotnet-common,dotnet-sampled-thread-time \
  --duration 00:00:00:15 -o /tmp/cpu.nettrace >/dev/null'
echo "== gcdump #2"
docker compose exec -T backend-1 sh -c 'cd /tmp && dotnet-gcdump collect -p 1 -o /tmp/heap-2.gcdump >/dev/null'
measured=$(( $(date +%s) - started ))

wait $k6 || true
grep -q '^vus_' "$out/k6.txt" && ! grep -q 'level=error' "$out/k6.txt" || { echo "k6 failed, see $out/k6.txt"; exit 1; }
wait $stats $activity || true
sleep 11   # сесії публікують статистику в pg_stat_database / pg_stat_statements із затримкою до 10 с

echo "== PostgreSQL statistics (window ${measured}s and the rest of the run)"
for db in postgres-replica postgres-shard-b-replica; do
  psql $db -c "SELECT calls, round(total_plan_time::numeric) AS plan_ms, round(total_exec_time::numeric) AS exec_ms,
      round((total_plan_time / greatest(calls, 1))::numeric, 3) AS plan_per_call_ms,
      round((total_exec_time / greatest(calls, 1))::numeric, 3) AS exec_per_call_ms,
      round((100 * total_plan_time / nullif(total_plan_time + total_exec_time, 0))::numeric, 1) AS plan_pct,
      left(regexp_replace(query, '\s+', ' ', 'g'), 120) AS query
    FROM pg_stat_statements ORDER BY total_plan_time + total_exec_time DESC LIMIT 6" > "$out/pg-stat-statements-$db.txt"
  psql $db -c "SELECT xact_commit, sessions, round(session_time::numeric / 1000) AS session_s,
      round(active_time::numeric / 1000, 1) AS active_s FROM pg_stat_database WHERE datname = current_database()" \
    > "$out/pg-stat-database-$db.txt"
done

page="SELECT p.id, p.title, p.status, p.is_public, p.creator_id, p.creator_username, (SELECT count(*)::int FROM options AS o WHERE p.id = o.poll_id), p.starts_at, p.ends_at, p.created_at FROM polls AS p WHERE p.is_public AND p.status <> 'draft' AND p.status = 'active' ORDER BY p.created_at DESC, p.id DESC LIMIT 20"
count="SELECT count(*)::int FROM polls AS p WHERE p.is_public AND p.status <> 'draft' AND p.status = 'active'"
# Тричі в одній сесії, у файл — останній раз: перший прогрів кеш каталогу системи в новому процесі.
for name in page count; do
  sql=${!name}
  psql postgres-replica -q -c "EXPLAIN (ANALYZE, BUFFERS) $sql" -c "EXPLAIN (ANALYZE, BUFFERS) $sql" \
    -c "EXPLAIN (ANALYZE, BUFFERS) $sql" | awk 'BEGIN{n=0} /QUERY PLAN/{n++} n==3' > "$out/explain-$name.txt"
done

echo "== artifacts from backend-1"
docker compose exec -T backend-1 sh -c 'cd /tmp && dotnet-trace convert /tmp/cpu.nettrace --format Speedscope -o /tmp/cpu >/dev/null \
  && dotnet-trace report /tmp/cpu.nettrace topN -n 30 > /tmp/topN-exclusive.txt \
  && dotnet-trace report /tmp/cpu.nettrace topN -n 30 --inclusive > /tmp/topN-inclusive.txt \
  && dotnet-gcdump report /tmp/heap-1.gcdump > /tmp/heap-1.txt && dotnet-gcdump report /tmp/heap-2.gcdump > /tmp/heap-2.txt'
for f in counters.csv cpu.nettrace cpu.speedscope.json topN-exclusive.txt topN-inclusive.txt heap-1.gcdump heap-2.gcdump heap-1.txt heap-2.txt; do
  docker compose cp "backend-1:/tmp/$f" "$out/$f" >/dev/null
done
python profiling/flamegraph.py "$out/cpu.speedscope.json" "$out/flamegraph-cpu.svg" --title "backend-1, catalog, $label" \
  --folded "$out/cpu.folded"
python profiling/flamegraph.py "$out/cpu.speedscope.json" "$out/flamegraph-all-threads.svg" --all --title "backend-1, catalog, $label"
python profiling/summary.py "$out"
