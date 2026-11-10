# Навантажувальні тести (лаба 5)

k6 у Docker, усередині мережі стеку, на власних ядрах ([ADR 0045](../docs/ai/decisions/0045-load-test-environment.md)).
Усі команди — з кореня репозиторію (Git Bash; у PowerShell без `export`).

```bash
export MSYS_NO_PATHCONV=1
C="-f docker-compose.yml -f load-tests/docker-compose.loadtest.yml"
docker compose $C up -d --build                          # стек з лімітами CPU / RAM і закріпленими ядрами
bash load-tests/env-spec.sh                              # специфікація середовища прогону
docker compose $C run --rm k6 run scenario-a-read.js     # A — читання
docker compose $C run --rm k6 run scenario-b-write.js    # B — голосування
docker compose $C run --rm k6 run scenario-c-workflow.js # C — наскрізний сценарій
```

| Файл | Що це |
|---|---|
| [`docker-compose.loadtest.yml`](docker-compose.loadtest.yml) | оверлей: ліміти й ядра кожного компонента, сервіс `k6` (профіль `loadtest`) |
| [`lib.js`](lib.js) | спільне: ступені навантаження, логін у `setup()`, підсумок по ступенях |
| [`scenario-a-read.js`](scenario-a-read.js) | **A, Read-Intensive:** 60 % результати (половина — гаряче опитування #1), 25 % деталі, 15 % каталог |
| [`scenario-b-write.js`](scenario-b-write.js) | **B, Write-Intensive:** голоси й зміни голосу 500 користувачів, 70 % — гаряче опитування #1 |
| [`scenario-c-workflow.js`](scenario-c-workflow.js) | **C, Complex Workflow:** каталог → деталі → голос → результати; у 20 % — повний цикл опитування автором |
| [`smoke.js`](smoke.js) | перевірка контуру, 5 VU × 10 с |
| [`open-model.js`](open-model.js) | голос сценарію B з фіксованою частотою прибуття (`-e RATE=1200`) — coordinated omission |
| [`run.sh`](run.sh) | один прогін + CPU контейнерів і стан сесій / транзакцій PostgreSQL кожні 5 с |
| [`series.sh`](series.sh) | уся серія вимірювань (≈ 55 хв), кожен прогін — на чистому стеку (ADR 0047) |
| [`report.py`](report.py) | таблиці у форматі методички, ресурси по ступенях, графіки Mermaid; `--compare` для серій |
| [`env-spec.sh`](env-spec.sh) | Baseline Environment Specification |
| [`docker-compose.loadtest-8cpu.yml`](docker-compose.loadtest-8cpu.yml) | лаба 6: те саме для машини з 8 логічними потоками ([ADR 0053](../docs/ai/decisions/0053-replica-load-comparison.md)); `OVERLAY=...` для `run.sh` |
| [`scenario-hot-shard.js`](scenario-hot-shard.js), [`hot-shard.sh`](hot-shard.sh), [`hot-shard-report.py`](hot-shard-report.py), [`docker-compose.loadtest-shards.yml`](docker-compose.loadtest-shards.yml) | лаба 7: Hot Shard — те саме навантаження на свіжі опитування з `Range` і `Buckets`, затримка й частка запитів по шардах (`X-Shard`), CPU / RAM Primary кожного шарду; ≈ 8 хв; результат — [`docs/lab7/hot-shard.md`](../docs/lab7/hot-shard.md) ([ADR 0056](../docs/ai/decisions/0056-hot-shard-experiment.md)) |
| [`series-lab6.sh`](series-lab6.sh) | лаба 6: Single Primary проти Primary + Replica, 17 прогонів, ≈ 95 хв; `mixed` — сценарій A під фоновим записом; результат — [`docs/lab6/load-comparison.md`](../docs/lab6/load-comparison.md) |

**Профіль навантаження** (однаковий для всіх сценаріїв): warm-up 20 с на 10 VU, далі плато по 40 с на 10 → 25 → 50 →
100 → 200 VU з паузою 5 с між ступенями. Кожен ступінь — окремий k6-scenario, тож метрики окремо по кожному.
Перевизначити: `-e LEVELS=10,50 -e STEP=20 -e WARMUP=10`; позначити серію: `-e RUN_TAG=cache-off`.
Користувачі не діляться між VU: у B — 200 слотів (відкрита модель обмежена 200 VU), у C — один VU = один користувач;
для C понад 500 VU — `USERS=800` і стек із `SEED_USERS=800` (інакше `setup()` зупиняє прогін). Лише частина серії:
`ONLY="c-extended open-1200" bash load-tests/series.sh`.

**Прогін з ресурсами:** `bash load-tests/run.sh scenario-b-write мітка [LEVELS=10,50 STEP=20]`, звіт —
`python load-tests/report.py load-tests/results/scenario-b-write-мітка-*.json`. Порівняння серій —
`python load-tests/report.py --compare "1 інстанс=a.json" "2 інстанси=b.json"`.

**Результати:** підсумок по ступенях — у консолі, повний JSON — у `load-tests/results/` (у `.gitignore`; відібрані
числа — у README репозиторію, розділ «Лабораторна 5»).

**Закрита модель.** VU шле наступний запит, щойно отримав відповідь (у A і B — без пауз, щоб знайти межу системи;
у C — паузи 100–300 мс між кроками). Наслідок — coordinated omission: коли система гальмує, генератор сам шле менше
запитів, і затримки тих, що «не відправились», у статистику не потрапляють (теорія — у посібнику до захисту).
