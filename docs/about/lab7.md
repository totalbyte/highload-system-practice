# Лабораторна робота № 7 — Шардинг і партиціювання даних

**Платформа опитувань** · PostgreSQL 17 (два шарди, кожен Primary + Replica) · ASP.NET Core 10 + EF Core · Redis 8 · HAProxy 3.4 · k6 1.3.0 · Docker Compose

Повний звіт — [README, розділ «Лабораторна 7»](../../README.md#лабораторна-7-шардинг-і-партиціювання-даних), звіти по пунктах — [`docs/lab7/`](../lab7/plan.md).
Рішення — ADR [0054](../ai/decisions/0054-shard-dataset-and-key.md) (ключ), [0055](../ai/decisions/0055-shard-topology-and-router.md) (топологія і роутер),
[0056](../ai/decisions/0056-hot-shard-experiment.md) (Hot Shard), [0057](../ai/decisions/0057-cross-shard-operations.md) (Cross-Shard), [0058](../ai/decisions/0058-resharding-model.md) (решардинг), [0059](../ai/decisions/0059-sharding-load-comparison.md) (вимірювання).

---

## 1. Результат

Опитування з варіантами й голосами розкладені по двох шардах за `poll_id`, стек стартує однією командою. Кожна операція з одним опитуванням іде рівно на один шард, каталог збирається з усіх. Гарячий шард відтворено і вирівняно віртуальними бакетами.
**Два шарди подвоюють запис і читання одного опитування (×1.9), а fan-out каталогу майже не масштабується (×1.1)** — масштабуються лише запити, які знають ключ.

## 2. Shard Key (2.1)

| Кандидат | Голос | Результати | Каталог | Чому так / ні |
|---|---|---|---|---|
| **`poll_id`** | 1 шард | 1 шард | усі | обрано: гарячі операції shard-local, `UNIQUE (poll_id, user_id)` і транзакція «голос + лічильник» лишаються локальними |
| `user_id` | 2 шарди | усі | усі | лічильник голосів належить опитуванню, а не користувачу |
| `votes.id` (сурогатний) | будь-де | усі | усі | сліпий ключ: голоси одного опитування розкидані, унікальність голосу не перевірити |
| `creator_id` | 1 шард | 1 шард | усі | низька Cardinality (20 авторів), великий автор = гарячий шард |

`users` не шардуємо: таблиця мала, а email і логін мають бути унікальними глобально. Наслідки для схеми: прибрано FK на `users`, ім'я автора скопійоване в `polls.creator_username` (замість розподіленого JOIN), id опитувань — з глобальної послідовності `poll_ids`.

**Де в репозиторії:** [ADR 0054](../ai/decisions/0054-shard-dataset-and-key.md), міграція `ShardPollAggregate` у [`Data/Migrations`](../../src/PollingPlatform.Api/Data/Migrations).

## 3. Топологія і Shard Router (2.2)

| Шард | Вузли | Що лежить |
|---|---|---|
| Shard A | `postgres` + `postgres-replica` | опитування своїх бакетів, `users`, послідовність `poll_ids` |
| Shard B | `postgres-shard-b` + `postgres-shard-b-replica` | опитування своїх бакетів |

Shard Router — у застосунку: `fmix64(poll_id) % 64` → бакет → шард. Стратегії `Range` / `Modulo` / `Hash` / `Buckets` перемикаються змінною `SHARD_STRATEGY`, `SHARD_COUNT=1` — один вузол. Кожен шард має свою маршрутизацію Primary / Replica з лаби 6. Заголовок `X-Shard` показує реальний шард запиту.

Перевірено: нові опитування лягають на обчислений шард і лише туди (прямо в БД), однаково з обох інстансів backend; голос і результати — один шард, каталог — `A,B`.

**Де в репозиторії:** [`Sharding/ShardRouter.cs`](../../src/PollingPlatform.Api/Sharding/ShardRouter.cs), [`Sharding/ShardContexts.cs`](../../src/PollingPlatform.Api/Sharding/ShardContexts.cs), [`docker-compose.yml`](../../docker-compose.yml), [`scripts/shard-routing-check.py`](../../scripts/shard-routing-check.py).

## 4. Розподіл даних і Hot Shard (2.3)

| Шард / Вузол | Кількість записів | Частка даних (%) | Частка Write Operations (%) |
|---|---|---|---|
| Shard A | 4934 | 42.2 | 55.6 |
| Shard B | 6758 | 57.8 | 44.4 |

Частку записів підтверджено двічі: за `X-Shard` і за лічильниками PostgreSQL кожного шарду (55.1 / 44.9 %).

| Hot Shard: нові опитування | `Range` (до) | `Buckets` (після) |
|---|---|---|
| частка запитів A / B | 0 / 100 % | 47 / 53 % |
| CPU Primary A / B | 1–3 % / 99 % | до 86 % / до 100 % |
| пропускна здатність | ≈ 520 RPS | ≈ 1000 RPS |
| p95 на 10 / 25 / 50 VU | 35 / 85 / 177 мс | 23 / 56 / 127 мс |

`Range` — партиціювання за часом: усі нові опитування, куди йдуть голоси, лягають на останній шард. Одне вірусне опитування — гарячий ключ, його не розкладе жоден хеш: читання бере кеш результатів, запис обмежений одним рядком лічильника.

**Де в репозиторії:** [`scripts/shard-distribution.py`](../../scripts/shard-distribution.py), [`load-tests/hot-shard.sh`](../../load-tests/hot-shard.sh), [`docs/lab7/hot-shard.md`](../lab7/hot-shard.md).

## 5. Cross-Shard запити і транзакції (2.4)

| Запит | Шарди | p50 на простої | Транзакцій БД на запит |
|---|---|---|---|
| деталі опитування (shard-local) | 1 | 2.9–4.1 мс | 2.8 на одному вузлі |
| каталог (fan-out) | 2 | 4.0 мс | 8.8 на двох вузлах |

| Shard B зупинено повністю | Результат |
|---|---|
| каталог | 200 за 16 мс, без опитувань B, заголовок `X-Shard-Unavailable: B` |
| опитування Shard A | працюють, голос записується |
| опитування Shard B | 503 `Shard Unavailable` за 6 мс |
| `/health` | 200 Degraded — backend-и лишаються в пулі |

Міжшардового запису в API немає: голос, лічильник і опитування на одному шарді (шард-локальний агрегат). 2PC не використовуємо (блокує всі шарди, поки координатор не вирішить); видалення акаунта розібрано як Saga.

**Де в репозиторії:** [`Polls/PollService.cs`](../../src/PollingPlatform.Api/Polls/PollService.cs) (`ListAsync`), [`scripts/cross-shard-check.py`](../../scripts/cross-shard-check.py), [`docs/lab7/cross-shard.md`](../lab7/cross-shard.md).

## 6. Решардинг і Consistent Hashing (2.5)

| Частка даних, що переїжджає | 2 → 3 | 3 → 4 | 4 → 5 |
|---|---|---|---|
| `key % N` | 66.7 % | 75.0 % | 80.0 % |
| кільце, 1 віртуальний вузол | 63.6 % | 2.1 % | 40.3 % |
| кільце, 100 віртуальних вузлів | 36.4 % | 25.2 % | 18.8 % |
| Virtual Buckets, 64 | 32.6 % | 24.9 % | 18.6 % |
| ідеал (M − N) / M | 33.3 % | 25.0 % | 20.0 % |

На реальних даних 2 → 3: 67 % рядків з modulo проти 36 % з бакетами.

**Де в репозиторії:** [`scripts/resharding-model.py`](../../scripts/resharding-model.py), [`docs/lab7/resharding.md`](../lab7/resharding.md).

## 7. Порівняння продуктивності (2.6)

| Режим | Single Node | 2 шарди | Приріст | Точка насичення |
|---|---|---|---|---|
| shard-local запис | ≈ 420 RPS | ≈ 780 RPS | ×1.9 | 10 → 25 VU |
| shard-local читання | ≈ 1400 RPS | ≈ 2700 RPS | ×1.9 | 10 → 25 VU |
| fan-out каталогу | ≈ 390 RPS | ≈ 420 RPS | ×1.1 | 10 → 10 VU |

0 % помилок у всіх прогонах. Кожен вузол БД обмежено одним ядром, щоб вузьким місцем була саме БД; числа не порівнюються з лабами 5 і 6.

**Де в репозиторії:** [`load-tests/scenario-shards.js`](../../load-tests/scenario-shards.js), [`load-tests/series-lab7.sh`](../../load-tests/series-lab7.sh), [`docs/lab7/load-comparison.md`](../lab7/load-comparison.md).

## 8. Теорія (п. 4 процедури)

| Поняття | У нашій системі |
|---|---|
| Партиціювання / шардинг / реплікація | партиціювання — поділ даних на частини; шардинг — частини на різних вузлах (у нас два шарди за `poll_id`); реплікація — копії однієї частини (Primary + Replica в кожному шарді, лаба 6) |
| Distributed JOIN | `polls → users` став міжвузловим — ім'я автора скопійоване в опитування |
| Unique constraints | працюють, коли ключ шардингу входить в унікальний ключ (`poll_id, user_id`) або таблиця не шардована (`users`) |
| 2PC | атомарно, але блокує; у PostgreSQL вимкнено за замовчуванням; не використовуємо |
| Saga | ланцюг локальних транзакцій з повторами; так виглядало б видалення акаунта |
| Consistent Hashing | кільце з віртуальними вузлами — переїжджає ≈ 1/M; у нас аналог — 64 віртуальні бакети |

## 9. Live-демо

```bash
docker compose down -v && docker compose up -d --build   # без ручних кроків; два шарди з репліками
python scripts/shard-routing-check.py --pause
python scripts/shard-distribution.py --live
python scripts/cross-shard-check.py --pause
python scripts/resharding-model.py --live
```

| Пункт процедури | Що показати |
|---|---|
| 1. Аргументація Shard Key | розділ 2 цієї сторінки, ADR 0054 |
| 2. Маршрутизація і розподіл, Hot Shard | `shard-routing-check.py`, `shard-distribution.py --live`, таблиця Hot Shard (живий прогін — `load-tests/hot-shard.sh`, ≈ 8 хв) |
| 3. Cross-Shard запити | `cross-shard-check.py` |
| 4. Теорія | розділ 8 цієї сторінки |
