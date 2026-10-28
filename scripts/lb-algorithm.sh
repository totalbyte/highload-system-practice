#!/usr/bin/env bash
# Лаба 3, П1-4 — live-перемикання алгоритму балансування однією командою (ADR 0034).
#
#   bash scripts/lb-algorithm.sh roundrobin|leastconn|weighted|source
#   bash scripts/lb-algorithm.sh            # показати поточний алгоритм і ваги
#
# Змінює рядок `balance` і вагу backend-1 у haproxy/haproxy.cfg, перевіряє конфіг тим самим HAProxy у контейнері
# `lb` і м'яко перезавантажує його (SIGUSR2 master-процесу): новий worker читає новий конфіг, старий доробляє свої
# з'єднання. Без перезбирання образу, без перезапуску контейнера і без помилок у клієнтів.
# weighted = roundrobin з вагою 3 на backend-1 (потужніший вузол), source — аналог IP Hash.
# Скрипт змінює файл у репозиторії: після демо повернути `roundrobin`.
set -euo pipefail
cd "$(dirname "$0")/.."
CFG=haproxy/haproxy.cfg

current() { grep -E '^    (balance|server backend-[0-9]+ )' "$CFG" | sed -E 's/^ +//; s/ backend-[0-9]+:8080//'; }

case "${1:-}" in
  "") current; exit 0 ;;
  roundrobin|leastconn|source) balance=$1; weight=1 ;;
  weighted) balance=roundrobin; weight=3 ;;
  *) echo "usage: bash scripts/lb-algorithm.sh [roundrobin|leastconn|weighted|source]" >&2; exit 2 ;;
esac

cp "$CFG" "$CFG.bak"
sed -i -E "s/^(    balance ).*/\1$balance/; s/^(    server backend-1 .* weight )[0-9]+/\1$weight/" "$CFG"
# Битий конфіг не повинен дійти до перезавантаження: перевіряємо його в контейнері, а при помилці повертаємо старий.
# MSYS_NO_PATHCONV: Git Bash на Windows інакше перепише шлях контейнера /usr/local/... на шлях Windows.
if ! MSYS_NO_PATHCONV=1 docker compose exec -T lb haproxy -c -q -f /usr/local/etc/haproxy/haproxy.cfg; then
  mv "$CFG.bak" "$CFG"
  echo "config check failed, haproxy.cfg restored, lb not reloaded" >&2
  exit 1
fi
rm "$CFG.bak"
docker compose kill -s USR2 lb >/dev/null 2>&1
echo "lb reloaded:"
current
