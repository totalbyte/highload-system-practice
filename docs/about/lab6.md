# Лабораторна робота № 6 — Реплікація БД і розділення читання та запису

**Платформа опитувань** · PostgreSQL 17 (потокова реплікація) · ASP.NET Core 10 + EF Core · Redis 8 · HAProxy 3.4 · k6 1.3.0 · Docker Compose

Повний звіт — [README, розділ «Лабораторна 6»](../../README.md#лабораторна-6-реплікація-бд-і-розділення-читання-та-запису), порівняльні таблиці — [`docs/lab6/load-comparison.md`](../lab6/load-comparison.md).
Рішення — ADR [0049](../ai/decisions/0049-primary-replica-topology.md) (топологія), [0050](../ai/decisions/0050-read-write-separation.md) (маршрутизація),
[0051](../ai/decisions/0051-read-after-write-sticky-routing.md) (Read-After-Write), [0052](../ai/decisions/0052-db-node-failures.md) (відмови), [0053](../ai/decisions/0053-replica-load-comparison.md) (вимірювання).

---

## 1. Результат

Primary і Replica працюють разом, стек стартує однією командою. Читання каталогу йдуть на репліку, записи й критичні читання — на Primary; автор бачить свої зміни навіть при відстаючій репліці. Система переживає втрату будь-якого вузла БД без помилок читання.
**Одна репліка такого самого розміру не збільшує пропускну здатність**, але під змішаним навантаженням удвічі знижує p95 читання до точки насичення; ціна — до 25 % пропускної здатності чистого запису.

## 2. Топологія (2.1)

| Вузол | Роль | Налаштування |
|---|---|---|
| `postgres` | Primary, усі записи | `wal_level=replica`, роль `replicator`, слот `replica_1`, `max_slot_wal_keep_size=1GB` |
| `postgres-replica` | read-only, асинхронно відтворює WAL | `pg_basebackup` на порожньому томі, `hot_standby_feedback=on` |

Перевірено: сід на обох вузлах однаковий (500 / 50 / 177 / 5596 рядків), INSERT, UPDATE, DELETE через API доходять до репліки, запис у неї відхиляється, `replay_lag` на простої 4–12 мс.

**Де в репозиторії:** [`docker-compose.yml`](../../docker-compose.yml), [`postgres/primary-init.sh`](../../postgres/primary-init.sh), [`postgres/replica-entrypoint.sh`](../../postgres/replica-entrypoint.sh), [`scripts/replication-check.py`](../../scripts/replication-check.py).

## 3. Read/Write Separation і класифікація (2.2, 2.3)

| Вузол | Операції |
|---|---|
| **Replica**, eventual | каталог, деталі опитування, результати при вимкненому кеші |
| **Primary**, strict | логін, реєстрація, `/me`, голос і перевірки перед ним, publish, close, delete, відповідь після запису, «мій голос», результати при промаху кешу |

Primary використовується за замовчуванням, на репліку веде лише один клас, тому помилка класифікації коштує навантаження, а не застарілих даних. Заголовок `X-DB-Node` показує вузол, до якого справді відкрито з'єднання. Незалежний доказ — лічильники PostgreSQL: за 300 читань каталогу на репліці ≈ +1206 транзакцій, на Primary ≈ +30 (фон).

**Промах кешу результатів читається лише з Primary.** Виміряно тимчасовим дослідом:

| MISS читає з | Застарілих раундів із 60, без штучної затримки | Із затримкою 200 мс |
|---|---|---|
| Replica | 11, 6 | 60 |
| Primary | 0 | 0 |

**Де в репозиторії:** [`Data/ReadDb.cs`](../../src/PollingPlatform.Api/Data/ReadDb.cs), [`Data/DbNodeTracking.cs`](../../src/PollingPlatform.Api/Data/DbNodeTracking.cs), [`Polls/PollService.cs`](../../src/PollingPlatform.Api/Polls/PollService.cs), [`Results/ResultsSingleFlight.cs`](../../src/PollingPlatform.Api/Results/ResultsSingleFlight.cs), [`scripts/rw-routing-check.py`](../../scripts/rw-routing-check.py).

## 4. Stale Read і Read-After-Write (2.3, 2.4)

**Session Sticky Routing:** після успішного запису читання користувача 5 с ідуть на Primary. Позначка в Redis, бо інстансів кілька. Керована затримка 3 с:

| Ситуація | Результат |
|---|---|
| Сторонній читач одразу після запису | 404 з репліки: Stale Read; бачить опитування через 2.5–2.9 с |
| Автор, захист увімкнено | 200 з Primary, на обох інстансах |
| Автор, захист вимкнено | 404 на власне опитування |
| Затримка 8 с більша за TTL 5 с | після TTL автор теж отримує 404: межа механізму |

**Де в репозиторії:** [`Data/StickySessions.cs`](../../src/PollingPlatform.Api/Data/StickySessions.cs), [`scripts/stale-read-demo.py`](../../scripts/stale-read-demo.py).

## 5. Відмови (2.5)

| Відмова | Читання | Запис і логін | Відновлення |
|---|---|---|---|
| Replica | 0 помилок, далі на Primary | працюють | 0.7–1.3 с |
| Primary | 0 помилок, на Replica | 503 `Read-Only Mode` за мілісекунди; перший запис 4–8 с | 1.3–2.3 с |
| Обидва | `/health` 503, контрольована відмова | те саме | 1.2–1.3 с |

Backend-и не перезапускаються. Автоматичного призначення нового лідера немає: завдання вимагає Read-Only Mode.

**Де в репозиторії:** [`Data/DbNodeMonitor.cs`](../../src/PollingPlatform.Api/Data/DbNodeMonitor.cs), [`scripts/db-failure-check.py`](../../scripts/db-failure-check.py).

## 6. Порівняння продуктивності (2.6)

17 прогонів скриптами лаби 5, 8 логічних потоків, чистий стек на кожен прогін, **0 % помилок**. Значення по прогонах.

| Сценарій | Показник | Single Primary | Primary + Replica |
|---|---|---|---|
| A, кеш увімк., 200 VU | RPS | 1870 | 1935 |
| A, кеш вимк., 200 VU | RPS | 1163; 1154 | 1091; 1149 |
| A + 15 VU запису, 50 VU | RPS читання | 1201; 1444 | 1372; 1336; 1345 |
| | p95 / p99 читання, мс | 158 / 256; 134 / 204 | **73 / 109; 78 / 147; 74 / 118** |
| 15 VU запису, весь прогін | RPS | 152; 127 | **197; 193; 198** |
| B, запис, 10 VU | RPS | **420; 427** | 324; 316; 296 |
| B, запис, 200 VU | RPS | 198; 198 | 185; 195; 184 |
| C, workflow, 200 VU | RPS | 687 | 659 |

**Точка насичення:** читання ≈ 25–50 VU і запис ≈ 10 VU в обох конфігураціях; змішане навантаження з реплікою ≈ 50 VU. Приросту RPS немає: читання лише переїжджають на вузол такого самого розміру. Вище насичення перевага в затримці зникає.

**Затримка реплікації:** до насичення щонайбільше 206 мс; вище — до 29.5 с із великим розкидом, причину не встановлено. Це межа Session Sticky (TTL 5 с), записана свідомо.

**Обмеження:** один ноутбук, сусідні потоки ділять фізичне ядро, 1–3 прогони на конфігурацію. Висновки — лише про великі різниці. Числа не порівнюються з лабою 5 (інша машина).

**Де в репозиторії:** [`load-tests/series-lab6.sh`](../../load-tests/series-lab6.sh), [`load-tests/docker-compose.loadtest-8cpu.yml`](../../load-tests/docker-compose.loadtest-8cpu.yml), [`docs/lab6/load-comparison.md`](../lab6/load-comparison.md).

## 7. Теорія (п. 4 процедури)

| Поняття | У нашій системі |
|---|---|
| Синхронна / асинхронна / напівсинхронна | асинхронна: COMMIT не чекає репліку; синхронна зупиняла б голоси при втраті репліки |
| Split-Brain | неможливий за побудовою: репліка сама не підвищується; ціна — записи стоять без Primary |
| CAP | без Primary запис обирає C (503), каталог обирає A (можливо застарілі дані) |
| PACELC | у нормальній роботі EL: низька затримка в обмін на Stale Read; Sticky точково повертає C |
| Вибір лідера, Raft | не реалізовано; 2 вузлів замало для більшості, потрібно 2f + 1; на практиці Patroni + etcd |

## 8. Live-демо

```bash
docker compose down -v && docker compose up -d --build   # ≈ 20 с зібраними образами, без ручних кроків
python scripts/replication-check.py --pause
python scripts/rw-routing-check.py --pause
python scripts/stale-read-demo.py --pause
python scripts/db-failure-check.py --pause
```

| Пункт процедури | Що показати |
|---|---|
| 1. Реплікація | `replication-check.py` |
| 2. Stale Read і Read-After-Write | `stale-read-demo.py` |
| 3. Відмови | `db-failure-check.py`, http://localhost:8404/stats |
| 4. Теорія | розділ 7 цієї сторінки |
