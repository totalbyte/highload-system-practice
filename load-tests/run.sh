#!/usr/bin/env bash
# Один прогін сценарію з паралельним зняттям ресурсів (лаба 5): CPU контейнерів і стан сесій PostgreSQL кожні 5 с.
#   bash load-tests/run.sh scenario-b-write [мітка серії] [додаткові -e для k6...]   # з кореня репозиторію, стек піднятий
# Результати: load-tests/results/<сценарій>-<мітка>-*.json (k6), …-resources.tsv і …-db.tsv (ресурси), …-env.txt.
cd "$(dirname "$0")/.." || exit 1
export MSYS_NO_PATHCONV=1
scenario=${1:?usage: run.sh <scenario-file-without-.js> [tag] [k6 -e options]}
tag=${2:-baseline}
shift 2 2>/dev/null || shift $#
# OVERLAY — розкладка ядер: 24-ядерна лаби 5 за замовчуванням, 8-потокова лаби 6 (ADR 0053).
C="-f docker-compose.yml -f ${OVERLAY:-load-tests/docker-compose.loadtest.yml}"
out="load-tests/results/${scenario}-${tag}"
mkdir -p load-tests/results

bash load-tests/env-spec.sh > "${out}-env.txt" 2>&1

# Час — epoch-секунди: report.py зіставляє їх з початком ступенів (startedAt у JSON k6 + розклад з lib.js).
# xact_total — накопичений лічильник транзакцій PostgreSQL: його приріст за ступінь = навантаження на БД.
(
  printf 'epoch_s\tcontainer\tcpu_pct\tmem\n' > "${out}-resources.tsv"
  printf 'epoch_s\tactive\twaiting_lock\twaiting_lwlock\twaiting_io\tclient_conns\txact_total\tidle_in_tx\n' > "${out}-db.tsv"
  # Лаба 6: навантаження на репліку і затримка реплікації. Порожні рядки, коли репліки немає (Single Primary).
  printf 'epoch_s\treplica_xact_total\treplay_lag_ms\tlag_bytes\n' > "${out}-replica.tsv"
  while :; do
    t=$(date +%s)
    docker stats --no-stream --format '{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}' 2>/dev/null |
      grep -E 'backend|lb-1|postgres|redis' | sed "s/^polling-platform-//; s/-1\t/\t/; s/^/${t}\t/" >> "${out}-resources.tsv"
    docker compose exec -T postgres psql -U polling -d polling -tA -F $'\t' -c \
      "SELECT ${t}, count(*) FILTER (WHERE state = 'active'),
              count(*) FILTER (WHERE state = 'active' AND wait_event_type = 'Lock'),
              count(*) FILTER (WHERE state = 'active' AND wait_event_type = 'LWLock'),
              count(*) FILTER (WHERE state = 'active' AND wait_event_type = 'IO'),
              count(*),
              (SELECT xact_commit + xact_rollback FROM pg_stat_database WHERE datname = current_database()),
              count(*) FILTER (WHERE state = 'idle in transaction')
       FROM pg_stat_activity WHERE backend_type = 'client backend' AND pid <> pg_backend_pid()" >> "${out}-db.tsv" 2>/dev/null
    if docker compose ps --status running --services 2>/dev/null | grep -q '^postgres-replica$'; then
      rx=$(docker compose exec -T postgres-replica psql -U polling -d polling -tAc \
        "SELECT xact_commit + xact_rollback FROM pg_stat_database WHERE datname = current_database()" 2>/dev/null | tr -d '\r')
      lag=$(docker compose exec -T postgres psql -U polling -d polling -tA -F $'\t' -c \
        "SELECT round(extract(epoch FROM replay_lag) * 1000, 1), pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) FROM pg_stat_replication" 2>/dev/null | tr -d '\r')
      printf '%s\t%s\t%s\n' "$t" "$rx" "$lag" >> "${out}-replica.tsv"
    fi
    sleep 5
  done
) &
sampler=$!
trap 'kill $sampler 2>/dev/null' EXIT

extra=()
for e in "$@"; do extra+=(-e "$e"); done
docker compose $C run --rm -e RUN_TAG="$tag" "${extra[@]}" k6 run --quiet "${scenario}.js"
