#!/bin/sh
# Підготовка Primary до реплікації (лаба 6, ADR 0049). Офіційний образ виконує цей файл із /docker-entrypoint-initdb.d
# лише один раз — коли том порожній, тому на томі, створеному до лаби 6, його немає: потрібен `docker compose down -v`.
set -e

# Окрема роль лише для реплікації: репліка не отримує пароль і права застосунку.
# Слот змушує Primary тримати WAL, доки репліка його не забере, тож короткий простій репліки не вимагає нового
# pg_basebackup. true = резервувати WAL одразу, а не з першого підключення.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -v password="$REPLICATION_PASSWORD" <<'SQL'
CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD :'password';
SELECT pg_create_physical_replication_slot('replica_1', true);
SQL

# Правило `host all all all` образу не покриває псевдобазу replication — потрібен окремий рядок.
echo "host replication replicator all scram-sha-256" >> "$PGDATA/pg_hba.conf"
