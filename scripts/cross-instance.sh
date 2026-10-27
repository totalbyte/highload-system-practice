#!/usr/bin/env bash
# Лаба 2, п. 2.5 — Cross-Instance Consistency: ланцюжок запитів, де кроки йдуть на різні інстанси, без sticky
# sessions (cookies не надсилаються, інстанс обирається портом). Кожен крок друкує X-Instance-ID і ключове поле.
#
#   bash scripts/cross-instance.sh
#
# Потрібні curl і python 3 (Git Bash на Windows підходить). Стек: docker compose up -d.

I1=${I1:-http://localhost:8080}
I2=${I2:-http://localhost:8082}

# step N METHOD URL [TOKEN] [JSON] — виконує запит, друкує інстанс і HTTP-код; тіло відповіді → $BODY.
step() {
  local n=$1 method=$2 url=$3 token=$4 json=$5
  local args=(-s -i -X "$method" "$url")
  [ -n "$token" ] && args+=(-H "Authorization: Bearer $token")
  [ -n "$json" ] && args+=(-H 'Content-Type: application/json' -d "$json")
  local response; response=$(curl "${args[@]}" | tr -d '\r')
  BODY=$(echo "$response" | tail -n 1)
  printf '%-3s %-6s %-36s %s, HTTP %s\n' "$n" "$method" "${url#http://localhost}" \
    "$(echo "$response" | grep -i '^x-instance-id:' | cut -d' ' -f2)" "$(echo "$response" | head -n 1 | cut -d' ' -f2)"
}

# field EXPR — поле з JSON останньої відповіді, EXPR — вираз Python над `d`.
field() { echo "$BODY" | python -I -c "import json,sys; d=json.load(sys.stdin); print($1)" | tr -d '\r'; }

step 1 POST "$I1/api/auth/login" "" '{"email":"user001@example.com","password":"Password123!"}'
TOKEN=$(field "d['accessToken']")

step 2 POST "$I1/api/polls" "$TOKEN" '{"title":"Cross-instance check","options":["A","B"],"endsAt":"2030-01-01T00:00:00Z"}'
POLL=$(field "d['id']"); OPTION=$(field "d['options'][0]['id']")
echo "    status: $(field "d['status']")"

step 3 GET "$I2/api/polls/$POLL" "$TOKEN"
echo "    status: $(field "d['status']")"

step 4 PATCH "$I2/api/polls/$POLL/publish" "$TOKEN"
echo "    status: $(field "d['status']")"

step 5 GET "$I1/api/polls/$POLL"
echo "    status: $(field "d['status']")"

step 6 GET "$I2/api/polls/$POLL/results"
echo "    totalVotes: $(field "d['totalVotes']")"

step 7 POST "$I1/api/polls/$POLL/vote" "$TOKEN" "{\"optionId\":$OPTION}"

step 8 GET "$I2/api/polls/$POLL/results"
echo "    totalVotes: $(field "d['totalVotes']")   (очікується 1)"
