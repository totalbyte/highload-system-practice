// Лаба 8, 2.2: Cache Stampede / Thundering Herd на гарячому опитуванні (ADR 0060).
// Інвалідація — те саме, що робить голос: INCR покоління в Redis (ADR 0041), після чого ключ значення ніхто не читає.
// Скільки разів агрегат після цього читали з БД, рахує не k6, а PostgreSQL (pg_stat_statements) — див. stampede.sh.
//
// MODE=burst (за замовчуванням, live-демо): VUS читачів чекають спільного моменту, за 50 мс до нього ключ скидається,
//   і всі читають одночасно. ROUNDS раундів з інтервалом PERIOD с; раунд 0 — без інвалідації (з'єднання, JIT).
// MODE=sustained (для матриці 2.7): VUS читачів без пауз протягом DURATION, ключ скидається кожні INTERVAL мс —
//   як голоси в гаряче опитування. Звідси RPS, p95 / p99 і помилки під потоком інвалідацій.
//
//   docker compose -f docker-compose.yml -f load-tests/docker-compose.loadtest-lab8.yml run --rm k6 run scenario-stampede.js
//   (зручніше — bash load-tests/stampede.sh <None|SingleFlight|...> [мітка] [-e ...])
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter } from 'k6/metrics';
import redis from 'k6/experimental/redis';
import { BASE, SUMMARY_TREND_STATS } from './lib.js';

const MODE = __ENV.MODE || 'burst';
const POLL = Number(__ENV.POLL || 1);
const VUS = Number(__ENV.VUS || 500);
const ROUNDS = Number(__ENV.ROUNDS || 5);
const PERIOD = Number(__ENV.PERIOD || 3);
const DURATION = __ENV.DURATION || '30s';
const INTERVAL = Number(__ENV.INTERVAL || 200);
const TAG = __ENV.RUN_TAG || 'run';

const GEN_KEY = `polling:results:gen:${POLL}`;
const redisClient = new redis.Client(__ENV.REDIS_URL || 'redis://redis:6379');
const invalidations = new Counter('invalidations');
const misses = new Counter('cache_miss');
// Читання з БД, що не належать до stampede: setup() прогріває кеш, і якщо ключа ще не було, це одне звернення.
const warmupLoads = new Counter('warmup_db_loads');

// Підметрики фази stampede потрапляють у підсумок лише з порогом — порожні пороги, як у lib.js.
const thresholds = {
  'http_req_duration{phase:stampede}': ['max>=0'],
  'http_req_failed{phase:stampede}': ['rate>=0'],
  'http_reqs{phase:stampede}': ['count>=0'],
};

export const options = {
  scenarios: MODE === 'burst'
    ? {
      readers: { executor: 'per-vu-iterations', exec: 'burstRead', vus: VUS, iterations: ROUNDS + 1, maxDuration: '10m' },
      invalidate: { executor: 'per-vu-iterations', exec: 'burstInvalidate', vus: 1, iterations: ROUNDS, maxDuration: '10m' },
    }
    : {
      readers: { executor: 'constant-vus', exec: 'sustainedRead', vus: VUS, duration: DURATION, gracefulStop: '10s' },
      invalidate: { executor: 'constant-vus', exec: 'sustainedInvalidate', vus: 1, duration: DURATION, gracefulStop: '1s' },
    },
  thresholds,
  summaryTrendStats: SUMMARY_TREND_STATS,
};

export function setup() {
  const r = http.get(`${BASE}/api/polls/${POLL}/results`, { tags: { name: 'setup' } });
  check(r, { 'setup: results 200': (x) => x.status === 200 });
  if (r.headers['X-Cache'] === 'MISS') warmupLoads.add(1);
  // Спільний відлік раундів для всіх VU: перший момент — із запасом на ініціалізацію 500 VU.
  return { start: Date.now() + 3000 };
}

function read(phase) {
  const r = http.get(`${BASE}/api/polls/${POLL}/results`, { tags: { name: 'results', phase } });
  check(r, { 'results 200': (x) => x.status === 200 });
  if (r.headers['X-Cache'] !== 'MISS') return;
  if (phase === 'stampede') misses.add(1);
  else warmupLoads.add(1);
}

const sleepUntil = (t) => sleep(Math.max(0, (t - Date.now()) / 1000));

export function burstRead(data) {
  sleepUntil(data.start + __ITER * PERIOD * 1000);
  read(__ITER === 0 ? 'warmup' : 'stampede');
}

export async function burstInvalidate(data) {
  sleepUntil(data.start + (__ITER + 1) * PERIOD * 1000 - 50);
  await redisClient.incr(GEN_KEY);
  invalidations.add(1);
}

export function sustainedRead() {
  read('stampede');
}

export async function sustainedInvalidate() {
  sleep(INTERVAL / 1000);
  await redisClient.incr(GEN_KEY);
  invalidations.add(1);
}

export function handleSummary(data) {
  const m = (name) => data.metrics[name] && data.metrics[name].values;
  const d = m('http_req_duration{phase:stampede}') || {};
  const reqs = (m('http_reqs{phase:stampede}') || {}).count || 0;
  const failed = (m('http_req_failed{phase:stampede}') || {}).rate || 0;
  const inv = (m('invalidations') || {}).count || 0;
  const miss = (m('cache_miss') || {}).count || 0;
  const seconds = MODE === 'burst' ? null : data.state.testRunDurationMs / 1000;
  const fmt = (v) => (v === undefined ? '-' : v.toFixed(1));
  let out = `\nscenario-stampede ${MODE}: poll ${POLL}, ${VUS} VUs, ${inv} invalidations, tag ${TAG}\n`;
  out += `  requests ${reqs}${seconds ? `, RPS ${(reqs / seconds).toFixed(0)}` : ''}, X-Cache MISS ${miss}` +
    ` (${inv ? (miss / inv).toFixed(1) : '-'} per invalidation), errors ${(failed * 100).toFixed(2)} %\n`;
  out += `  latency ms: avg ${fmt(d.avg)}  p50 ${fmt(d.med)}  p95 ${fmt(d['p(95)'])}  p99 ${fmt(d['p(99)'])}  max ${fmt(d.max)}\n`;
  return {
    stdout: out,
    [`${__ENV.K6_SUMMARY_DIR || 'results'}/stampede-${MODE}-${TAG}.json`]: JSON.stringify(data, null, 1),
  };
}
