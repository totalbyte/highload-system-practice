#!/bin/sh
# Старт репліки без ручних кроків (лаба 6, ADR 0049): на порожньому томі — копія Primary через pg_basebackup, далі
# стандартний entrypoint образу. Він бачить готовий каталог, пропускає initdb і запускає PostgreSQL у режимі standby.
set -e

PGDATA=/var/lib/postgresql/data

if [ ! -s "$PGDATA/PG_VERSION" ]; then
  # Перевірка по TCP, а не healthcheck з depends_on: під час першої ініціалізації Primary приймає лише локальні
  # підключення, і healthcheck через сокет уже зелений, хоча роль replicator і слот ще не створено.
  until pg_isready -h postgres -p 5432 -q; do
    echo "replica: waiting for the primary..."
    sleep 1
  done

  mkdir -p "$PGDATA"
  chown postgres:postgres "$PGDATA"
  chmod 700 "$PGDATA"

  # -R записує primary_conninfo і standby.signal: саме вони вмикають режим репліки.
  # -S використовує слот із primary-init.sh, -X stream передає WAL, що з'явився під час копіювання.
  echo "replica: pg_basebackup from the primary..."
  PGPASSWORD="$REPLICATION_PASSWORD" gosu postgres pg_basebackup \
    -h postgres -p 5432 -U replicator -D "$PGDATA" -S replica_1 -X stream -R -c fast
fi

exec docker-entrypoint.sh "$@"
