#!/usr/bin/env bash
# Baseline Environment Specification (лаба 5, 2.2.2): фіксує, на чому зроблено прогін. Запускати з кореня репозиторію
# перед кожною серією; вивід зберегти поруч з результатами:  bash load-tests/env-spec.sh > load-tests/results/env.txt
cd "$(dirname "$0")/.." || exit 1
export MSYS_NO_PATHCONV=1

echo "=== Host (Docker engine) ==="
docker info --format 'CPUs: {{.NCPU}}  RAM: {{.MemTotal}} bytes  OS: {{.OperatingSystem}}  Docker: {{.ServerVersion}}'

echo
echo "=== Containers: CPU set / CPU limit / memory limit ==="
printf '%-34s %-8s %-6s %-10s %s\n' container cpuset cpus memory image
for id in $(docker compose ps -q); do
  docker inspect -f '{{.Name}}|{{.HostConfig.CpusetCpus}}|{{.HostConfig.NanoCpus}}|{{.HostConfig.Memory}}|{{.Config.Image}}' "$id" |
    awk -F'|' '{ cpus = $3 == 0 ? "-" : $3 / 1e9; mem = $4 == 0 ? "-" : int($4 / 1048576) "M";
                 printf "%-34s %-8s %-6s %-10s %s\n", substr($1, 2), ($2 == "" ? "-" : $2), cpus, mem, $5 }'
done

echo
echo "=== Backend pool (HAProxy) ==="
curl -s "http://127.0.0.1:${LB_STATS_PORT:-8404}/stats;csv" | awk -F, '$1 == "be_api" && $2 ~ /^backend-/ { printf "%s %s  ", $2, $18 } END { print "" }'
echo "balance: $(grep -m1 -E '^    balance ' haproxy/haproxy.cfg | awk '{print $2}')"

echo
echo "=== Backend config (backend-1) ==="
docker compose exec -T backend-1 printenv ConnectionStrings__Postgres | grep -o 'Maximum Pool Size=[0-9]*'
echo "ResultsCache__Enabled=$(docker compose exec -T backend-1 printenv ResultsCache__Enabled)"
echo "Diagnostics__ArtificialDelayMs=$(docker compose exec -T backend-1 printenv Diagnostics__ArtificialDelayMs || echo unset)"

echo
echo "=== PostgreSQL ==="
docker compose exec -T postgres psql -U polling -d polling -tAc \
  "SELECT 'version ' || current_setting('server_version') || ', max_connections ' || current_setting('max_connections') || ', shared_buffers ' || current_setting('shared_buffers')"
docker compose exec -T postgres psql -U polling -d polling -tAc \
  "SELECT 'users ' || (SELECT count(*) FROM users) || ', polls ' || (SELECT count(*) FROM polls) || ', votes ' || (SELECT count(*) FROM votes)"

echo
echo "=== Redis ==="
docker compose exec -T redis redis-cli INFO server | grep -E '^redis_version' | tr -d '\r'
echo "keys: $(docker compose exec -T redis redis-cli DBSIZE | tr -d '\r'), save: '$(docker compose exec -T redis redis-cli CONFIG GET save | tail -1 | tr -d '\r')', maxmemory-policy: $(docker compose exec -T redis redis-cli CONFIG GET maxmemory-policy | tail -1 | tr -d '\r')"
