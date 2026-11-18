// Лаба 8, 2.3 / 2.5: Cache Avalanche — синхронне спливання TTL багатьох ключів (ADR 0062).
// setup() одночасно прогріває кеш результатів усіх опитувань 1..POLLS (чернетки дають 404 і відкидаються): ключі
// записані в одну секунду. Далі VUS читачів без пауз читають результати випадкових опитувань. Голосів немає, тож ключі
// зникають лише за TTL: без розкиду (RESULTS_TTL_JITTER=0) усі разом кожні 10 с — хвилі промахів і звернень до БД;
// з розкидом ±20 % хвилі розмазуються. Затримка і промахи — по секундах від кінця прогріву; звернення до БД і активні
// сесії PostgreSQL знімає avalanche.sh, звіт — avalanche-report.py.
//   bash load-tests/avalanche.sh <jitter> [мітка]       (стек із SEED_POLLS=1000, див. runbook)
import http from 'k6/http';
import { check } from 'k6';
import { Counter } from 'k6/metrics';
import { BASE, SUMMARY_TREND_STATS } from './lib.js';

const POLLS = Number(__ENV.POLLS || 1000);
const VUS = Number(__ENV.VUS || 300);
const SECONDS = Number(__ENV.SECONDS || 60);
const TAG = __ENV.RUN_TAG || 'run';
const misses = new Counter('cache_miss');

// Підметрика на кожну секунду — порожні пороги, як у lib.js, інакше в підсумку їх не буде.
const thresholds = {
  'http_req_duration{name:results}': ['max>=0'],
  'http_req_failed{name:results}': ['rate>=0'],
};
for (let s = 0; s <= SECONDS; s++) {
  thresholds[`http_req_duration{sec:${s}}`] = ['max>=0'];
  thresholds[`cache_miss{sec:${s}}`] = ['count>=0'];
}

export const options = {
  scenarios: {
    readers: { executor: 'constant-vus', exec: 'read', vus: VUS, duration: `${SECONDS}s`, gracefulStop: '5s' },
  },
  // Прогрів пачками по 100 паралельних запитів: усі ключі мають з'явитися в кеші майже одночасно.
  batch: 100,
  batchPerHost: 100,
  setupTimeout: '120s',
  thresholds,
  summaryTrendStats: [...SUMMARY_TREND_STATS, 'count'],
};

export function setup() {
  const ids = [];
  for (let from = 1; from <= POLLS; from += 100) {
    const batch = [];
    for (let id = from; id < Math.min(from + 100, POLLS + 1); id++) {
      batch.push(['GET', `${BASE}/api/polls/${id}/results`, null, { tags: { name: 'warmup' } }]);
    }
    http.batch(batch).forEach((r, i) => { if (r.status === 200) ids.push(from + i); });
  }
  return { ids, start: Date.now() };
}

export function read(data) {
  const id = data.ids[Math.floor(Math.random() * data.ids.length)];
  const sec = String(Math.floor((Date.now() - data.start) / 1000));
  const r = http.get(`${BASE}/api/polls/${id}/results`, { tags: { name: 'results', sec } });
  check(r, { 'results 200': (x) => x.status === 200 });
  if (r.headers['X-Cache'] === 'MISS') misses.add(1, { sec });
}

export function handleSummary(data) {
  const v = (name) => (data.metrics[name] ? data.metrics[name].values : undefined);
  const rows = [];
  for (let s = 0; s <= SECONDS; s++) {
    const d = v(`http_req_duration{sec:${s}}`);
    if (!d || !d.count) continue;
    rows.push({ sec: s, reqs: d.count, misses: (v(`cache_miss{sec:${s}}`) || {}).count || 0, p95: d['p(95)'], max: d.max });
  }
  const all = v('http_req_duration{name:results}');
  const failed = (v('http_req_failed{name:results}') || {}).rate || 0;
  const out = {
    tag: TAG, keys: data.setup_data.ids.length, start: data.setup_data.start, vus: VUS, seconds: SECONDS,
    p95: all['p(95)'], p99: all['p(99)'], errors: failed, rows,
  };
  return {
    stdout: `\nscenario-avalanche ${TAG}: ${out.keys} keys, ${VUS} VUs, ${SECONDS} s, errors ${(failed * 100).toFixed(2)} %\n`,
    [`${__ENV.K6_SUMMARY_DIR || 'results'}/avalanche-${TAG}.json`]: JSON.stringify(out, null, 1),
  };
}
