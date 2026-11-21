# Профілювання (лабораторна 9)

Цикл Symptom → Hypotheses → Instrumentation → Evidence → Root Cause → Optimization → Regression Verification для одного
симптому. Рішення — ADR [0065](../docs/ai/decisions/0065-lab9-symptom-and-db-instrumentation.md)–[0070](../docs/ai/decisions/0070-migration-advisory-lock.md),
порівняння до / після — [`ab-report.md`](ab-report.md).

## 1. Симптом

У лабі 7 каталог `GET /api/polls` на двох шардах насичувався вже на 10 VU при ≈ 410 RPS. Обидві репліки працювали на
98–101 % свого ядра, p95 на 200 VU сягав 853 мс, а другий шард дав лише ×1.1. При цьому на кожному шарді лише кілька
десятків опитувань. За `docker stats` це ≈ 2.3 мс CPU репліки на один запит каталогу — забагато для таких маленьких запитів.

## 2. Гіпотези

| | Гіпотеза | Чим перевіряю |
|---|---|---|
| H1 | неефективний план: повне сканування `polls` і сортування | EXPLAIN ANALYZE |
| H2 | N+1 у SQL: кількість варіантів рахується підзапитом для кожного рядка | EXPLAIN ANALYZE (loops) |
| H3 | кожен запит заново розбирається й планується, бо Npgsql не готує запити | `pg_stat_statements` з `track_planning`, Npgsql `prepared_ratio`, `pgbench` simple / extended / prepared |
| H4 | пул з'єднань: churn нових з'єднань або очікування вільного | лічильники пулу Npgsql, `pg_stat_database.sessions`, `pg_stat_activity` |
| H5 | сам backend: CPU, GC, серіалізація, злиття fan-out | flame graph, `dotnet-counters`, два знімки купи, траси Jaeger |

## 3. Інструменти

| Що | Чим | Де |
|---|---|---|
| CPU backend | `dotnet-trace` (час потоків ~100 Гц) → flame graph лише з `CPU_TIME` | `*/flamegraph-cpu.svg`, `*/flamegraph-all-threads.svg`, `*/topN-*.txt` (сирий профіль і folded stacks відтворює `collect.sh`, у git їх немає) |
| Пам'ять backend | `dotnet-counters` (алокації, GC, паузи), `dotnet-gcdump` на початку й наприкінці | `*/counters.csv`, `*/heap-1.gcdump`, `*/heap-2.gcdump`, `*/heap-*.txt` |
| БД | `pg_stat_statements` (планування окремо), EXPLAIN (ANALYZE, BUFFERS), `pg_stat_activity` | `*/pg-stat-statements-*.txt`, `*/explain-*.txt`, `*/pg-activity-replica-a.tsv` |
| Трасування | OpenTelemetry → Jaeger, декомпозиція `traces.py` | `*/traces.md`, `*/trace-example.json` |
| Контрольний експеримент | `pgbench` з тими самими двома запитами на репліці | `pgbench/` |
| Ресурси контейнерів | `docker stats` кожні 5 с | `*/docker-stats.tsv` |

Усе знімається одним скриптом під тим самим навантаженням (каталог, 50 VU, одне ядро на вузол БД):

```bash
bash profiling/collect.sh baseline                         # DB_MAX_AUTO_PREPARE=0 у середовищі — конфігурація «до»
bash profiling/collect.sh optimized                        # за замовчуванням, з оптимізацією
TRACING_ENABLED=true docker compose --profile tracing up -d && python profiling/traces.py profiling/baseline
bash profiling/pgbench/run.sh
```

Зведення кожного прогону — `baseline/summary.md` і `optimized/summary.md`.

## 4. Докази

**H1 — спростовано.** EXPLAIN ANALYZE сторінки каталогу ([`baseline/explain-page.txt`](baseline/explain-page.txt)):
`Index Scan Backward using ix_polls_status_created_at`, сортування лише інкрементне за вже відсортованим індексом,
виконання 0.50 мс. Повного сканування `polls` немає.

**H2 — є, але дешево.** У тому ж плані `SubPlan 1` виконується `loops=13` разів (по разу на рядок сторінки) — це N+1
усередині SQL, але кожен прохід 0.017–0.020 мс. На такому обсязі даних це не причина.

**H3 — підтверджено.** `pg_stat_statements` репліки A за вікно прогону ([`baseline/pg-stat-statements-postgres-replica.txt`](baseline/pg-stat-statements-postgres-replica.txt)):

| Запит | Викликів | Планування, мс | Виконання, мс | Частка планування |
|---|---|---|---|---|
| сторінка каталогу | 38 958 | 14 734 | 15 866 | 48 % |
| підрахунок | 38 948 | 5 687 | 3 687 | 61 % |
| `DISCARD ALL` (скидання з'єднання пулом) | 77 904 | — | 1 991 | — |

Npgsql `prepared_ratio` = 0 % на обох пулах реплік ([`baseline/summary.md`](baseline/summary.md)). Окремий контрольний
експеримент — `pgbench` на тій самій репліці з тими самими двома запитами ([`pgbench/results.txt`](pgbench/results.txt)):

| Протокол | Запитів каталогу / с | Затримка |
|---|---|---|
| simple | 822 | 24.3 мс |
| extended — так працює Npgsql без підготовки | 717 | 27.9 мс |
| prepared | **1723** | **11.6 мс** |

Та сама база на тому самому ядрі (`cpu.max 100000 100000` — рівно одне ядро) обслуговує у 2.4 раза більше, якщо запит
не треба щоразу розбирати й планувати. Розвідувальний прогін того самого дня дав 950 проти 2514 (×2.6).

**H4 — наслідок, а не причина.** Пул однієї репліки тримає ≈ 24 з 30 з'єднань зайнятими, бо репліка відповідає повільно;
нових сесій — лише від монітора вузлів (≈ 2–3 на секунду, `pg_stat_database.sessions` = 256 за прогін); черга пулу
потоків — 0.2.

**H5 — спростовано.** `dotnet-counters`: GC-паузи 0.94 % часу, 42 МБ/с алокацій, купа живих об'єктів 10.2 → 10.7 МБ за
вікно (витоку немає). Лише 10.9 % часу потоків — виконання керованого коду (`CPU_TIME`), решта — очікування на БД;
[flame graph](baseline/flamegraph-cpu.svg) показує, що й цей CPU — звичайний шлях запиту (Kestrel → контролер →
`PollService.ListAsync` → EF → Npgsql). Трасування ([`baseline/traces.md`](baseline/traces.md)): з 8.0 мс запиту
5.1 мс — SQL, 2.9 мс — backend.

## 5. Root Cause

Кожен запит каталогу на кожному шарді — два оператори, які PostgreSQL щоразу заново розбирає і планує, бо Npgsql
надсилає їх без підготовки, а після кожного повернення з'єднання в пул `DISCARD ALL` скидає стан сесії. На маленьких
даних планування коштує стільки ж, скільки виконання, і саме воно з'їдає ядро репліки.

## 6. Оптимізація

Один параметр рядка підключення (ADR [0068](../docs/ai/decisions/0068-auto-prepare-root-cause.md)):
`Max Auto Prepare=20` — Npgsql сам готує найчастіші запити кожного з'єднання і зберігає їх між поверненнями в пул.
Вимикач для A/B — `DB_MAX_AUTO_PREPARE=0`.

Після неї (той самий прогін, [`optimized/summary.md`](optimized/summary.md)): `prepared_ratio` 100 %, планування сторінки на
репліці A — 71 мс замість 14 734 мс, `DISCARD ALL` зник.

## 7. Повторний експеримент (A/B)

Ті самі умови, що й у лабі 7: одне ядро на вузол БД, чистий стек на кожен прогін, каталог 3 рази «до» і 3 рази «після» через
один, плюс по одному прогону запису й читання для перевірки регресії (`profiling/ab-series.sh`, ADR [0069](../docs/ai/decisions/0069-lab9-ab-verification.md)).
Повні таблиці по ступенях і CPU кожного вузла — [`ab-report.md`](ab-report.md).

Каталог, середнє з трьох повторів, 50 VU:

| Метрика / Показник | До оптимізації (Baseline) | Після оптимізації (Optimized) | Дельта (Зміна %) |
|---|---|---|---|
| Throughput (RPS) | 362 | 570 | +57.5 % |
| p95 Latency | 233.1 мс | 150.7 мс | −35.4 % |
| p99 Latency | 325.3 мс | 207.6 мс | −36.2 % |
| Error Rate (%) | 0.00 | 0.00 | — |
| CPU реплік A / B, % ядра (на 100 VU) | 97 / 101 | 96 / 102 | репліки й далі насичені, але обслуговують на 41 % більше запитів |
| CPU backend, % (з 200) / пам'ять, МіБ (на 100 VU) | 115 / 156 | 139 / 156 | CPU росте разом з RPS, пам'ять та сама |

На всіх ступенях 10–200 VU: RPS +41 … +58 %, p95 −17 … −35 %, p99 −17 … −36 %, помилок 0. Точка насичення каталогу лишилася
на 10 VU, але на 553 RPS замість 391: каталог і далі fan-out, просто кожен його запит дешевший для реплік.

**Регресія.** Запис голосів: RPS +31 … +81 %, p95 −11 … −42 %. Деталі опитування: RPS +44 … +136 %, p95 −35 … −63 %. Гірше
не стало ніде, бо підготовка допомагає кожному повторюваному запиту, а не лише каталогу. Побічний ефект: на деталях
опитування backend-и після зміни доходять до ≈ 200 % своїх двох ядер — вузьке місце цього шляху перемістилося з реплік на
backend.

**Компроміси (trade-offs).** Скидання з'єднання при поверненні в пул тепер чотири легкі команди замість одного
`DISCARD ALL`; кожен процес PostgreSQL тримає до 20 підготовлених операторів з планами (трохи більше пам'яті); generic plan
однаковий для всіх значень параметра (ризик для сильно нерівномірних даних); підготовлені запити несумісні з PgBouncer у
transaction mode (його в нас немає). Деталі — ADR [0068](../docs/ai/decisions/0068-auto-prepare-root-cause.md).
