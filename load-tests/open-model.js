// Відкрита модель навантаження (лаба 5, теорія: coordinated omission). Той самий запит, що в сценарії B (голос),
// але не «N користувачів по колу», а фіксована частота прибуття запитів — як у реальному світі, де нові користувачі
// приходять незалежно від того, чи встигає система.
//   docker compose -f docker-compose.yml -f load-tests/docker-compose.loadtest.yml run --rm -e RATE=1500 k6 run open-model.js
//
// Закрита модель (VU) чекає відповіді перед наступним запитом: коли система гальмує, генератор сам шле менше, і
// затримки запитів, які «мали б» прийти в цей час, у статистику не потрапляють (coordinated omission). Тут k6
// запускає ітерації за розкладом: якщо вільних VU немає, ітерація пропускається (dropped_iterations), а затримка
// чергу вже містить — так видно справжню ціну перевантаження.
import { vote, setup as writeSetup, SLOTS } from './scenario-b-write.js';
import { SUMMARY_TREND_STATS } from './lib.js';

const rate = Number(__ENV.RATE || 1000);
const duration = __ENV.DURATION || '40s';

export const options = {
  scenarios: {
    warmup: { executor: 'constant-vus', exec: 'vote', vus: 10, duration: '15s', gracefulStop: '3s' },
    open: {
      executor: 'constant-arrival-rate', exec: 'vote', rate, timeUnit: '1s', duration, startTime: '20s',
      // Не більше VU, ніж слотів користувачів у scenario-b-write.js: інакше два VU голосували б тим самим користувачем.
      preAllocatedVUs: SLOTS, maxVUs: SLOTS, gracefulStop: '5s',
    },
  },
  thresholds: {
    'http_req_duration{scenario:open}': ['max>=0'],
    'http_req_failed{scenario:open}': ['rate>=0'],
    'http_reqs{scenario:open}': ['count>=0'],
  },
  summaryTrendStats: SUMMARY_TREND_STATS,
  setupTimeout: '180s',
};

export const setup = writeSetup;
export { vote };

export function handleSummary(data) {
  const d = data.metrics['http_req_duration{scenario:open}'].values;
  const reqs = data.metrics['http_reqs{scenario:open}'].values.count;
  const dropped = data.metrics.dropped_iterations ? data.metrics.dropped_iterations.values.count : 0;
  const vus = data.metrics.vus_max ? data.metrics.vus_max.values.max : '-';
  const seconds = parseInt(duration, 10);
  const out = `\nopen model: target ${rate} req/s for ${seconds}s\n` +
    `sent ${reqs} (${Math.round(reqs / seconds)} req/s), dropped iterations ${dropped}, VUs used up to ${vus}\n` +
    `latency ms: avg ${d.avg.toFixed(1)}  p50 ${d.med.toFixed(1)}  p95 ${d['p(95)'].toFixed(1)}  ` +
    `p99 ${d['p(99)'].toFixed(1)}  max ${d.max.toFixed(1)}\n`;
  const { tokens, ...setupData } = data.setup_data || {};
  const stamp = new Date().toISOString().replace(/[:.]/g, '-');
  return {
    stdout: out,
    [`results/open-model-${rate}rps-${stamp}.json`]: JSON.stringify({ ...data, setup_data: setupData }, null, 1),
  };
}
