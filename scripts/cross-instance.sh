#!/usr/bin/env bash
# Лаба 2, п. 2.5 — Cross-Instance Consistency: ланцюжок запитів, де кроки йдуть на різні інстанси, без sticky
# sessions (cookies не надсилаються). Кожен крок друкує X-Instance-ID, HTTP-код і ключове поле, у кінці — підсумок.
#
#   bash scripts/cross-instance.sh
#
# З лаби 3 обидві адреси за замовчуванням — балансувальник: інстанс для кожного кроку обирає HAProxy (round robin),
# а X-Instance-ID показує, що кроки потрапили на різні інстанси. Конкретний інстанс, як у лабі 2, — лише з
# docker-compose.debug.yml: I1=http://localhost:8091 I2=http://localhost:8092 bash scripts/cross-instance.sh
#
# Потрібні curl і python 3 (Git Bash на Windows підходить). Стек: docker compose up -d. Код виходу 0 = 8 / 8.

I1=${I1:-http://localhost:8080}
I2=${I2:-http://localhost:8080}
PASSED=0
INSTANCES=()

# step N METHOD URL [TOKEN] [JSON] — виконує запит, друкує інстанс і HTTP-код; тіло відповіді → $BODY, код → $CODE.
step() {
  local n=$1 method=$2 url=$3 token=$4 json=$5
  local args=(-s -i -X "$method" "$url")
  [ -n "$token" ] && args+=(-H "Authorization: Bearer $token")
  [ -n "$json" ] && args+=(-H 'Content-Type: application/json' -d "$json")
  local response; response=$(curl "${args[@]}" | tr -d '\r')
  BODY=$(echo "$response" | tail -n 1)
  CODE=$(echo "$response" | head -n 1 | cut -d' ' -f2)
  local instance; instance=$(echo "$response" | grep -i '^x-instance-id:' | cut -d' ' -f2)
  INSTANCES+=("${instance:-none}")
  printf '%-3s %-6s %-36s %s, HTTP %s\n' "$n" "$method" "${url#http://localhost}" "$instance" "$CODE"
}

# field EXPR — поле з JSON останньої відповіді, EXPR — вираз Python над `d`; порожньо, якщо тіло не JSON.
field() { echo "$BODY" | python -I -c "import json,sys; d=json.load(sys.stdin); print($1)" 2>/dev/null | tr -d '\r'; }

# check CODE [ACTUAL EXPECTED] — крок пройшов, якщо HTTP-код (і, за потреби, ключове поле) такі, як очікується.
check() {
  if [ "$CODE" = "$1" ] && [ "${2-}" = "${3-}" ]; then
    PASSED=$((PASSED + 1))
  else
    echo "    FAIL: expected HTTP $1${3:+ and $3}"
  fi
}

step 1 POST "$I1/api/auth/login" "" '{"email":"user001@example.com","password":"Password123!"}'
TOKEN=$(field "d['accessToken']")
check 200

step 2 POST "$I1/api/polls" "$TOKEN" '{"title":"Cross-instance check","options":["A","B"],"endsAt":"2030-01-01T00:00:00Z"}'
POLL=$(field "d['id']"); OPTION=$(field "d['options'][0]['id']")
STATUS=$(field "d['status']"); echo "    status: $STATUS"
check 201 "$STATUS" draft

step 3 GET "$I2/api/polls/$POLL" "$TOKEN"
STATUS=$(field "d['status']"); echo "    status: $STATUS"
check 200 "$STATUS" draft

step 4 PATCH "$I2/api/polls/$POLL/publish" "$TOKEN"
STATUS=$(field "d['status']"); echo "    status: $STATUS"
check 200 "$STATUS" active

step 5 GET "$I1/api/polls/$POLL"
STATUS=$(field "d['status']"); echo "    status: $STATUS"
check 200 "$STATUS" active

step 6 GET "$I2/api/polls/$POLL/results"
TOTAL=$(field "d['totalVotes']"); echo "    totalVotes: $TOTAL"
check 200 "$TOTAL" 0

step 7 POST "$I1/api/polls/$POLL/vote" "$TOKEN" "{\"optionId\":$OPTION}"
check 201

step 8 GET "$I2/api/polls/$POLL/results"
TOTAL=$(field "d['totalVotes']"); echo "    totalVotes: $TOTAL   (очікується 1)"
check 200 "$TOTAL" 1

echo
echo "steps passed: $PASSED / 8; served by: $(printf '%s\n' "${INSTANCES[@]}" | sort | uniq -c | awk '{printf "%s x%s  ", $2, $1}')"
[ "$PASSED" = 8 ]
