// Лаба 8, 2.6: Cache Penetration — потік запитів до результатів опитувань, яких немає (ADR 0063).
// Без негативного кешу кожен такий запит промахується в Redis і йде в PostgreSQL; з ним «немає» кешується на ≈ 30 с.
// IDS=N (за замовчуванням 100) — запити по колу до N неіснуючих id від 10 000 000 (типова атака / биті посилання);
// IDS=0 — кожен запит до нового id: негативний кеш тут не допомагає, і видно, скільки пам'яті Redis він з'їдає.
// Звернення до БД і пам'ять Redis рахує penetration.sh.
//   bash load-tests/penetration.sh <true|false> [-e IDS=0 -e VUS=200 -e DURATION=30s]
import http from 'k6/http';
import { check } from 'k6';
import { BASE, SUMMARY_TREND_STATS } from './lib.js';

const VUS = Number(__ENV.VUS || 200);
const DURATION = __ENV.DURATION || '30s';
const IDS = Number(__ENV.IDS ?? 100);
const BASE_ID = 10000000;
const TAG = __ENV.RUN_TAG || 'run';
// 404 — очікувана відповідь, помилка — усе інше (503, таймаути).
const expect404 = http.expectedStatuses(404);

export const options = {
  scenarios: { attack: { executor: 'constant-vus', exec: 'probe', vus: VUS, duration: DURATION } },
  thresholds: { 'http_req_duration{name:missing}': ['max>=0'], 'http_req_failed{name:missing}': ['rate>=0'] },
  summaryTrendStats: SUMMARY_TREND_STATS,
};

export function probe() {
  // IDS=0: унікальний id на кожен запит (VU × 10^6 + номер ітерації) — жоден не повторюється.
  const id = IDS > 0 ? BASE_ID + Math.floor(Math.random() * IDS) : BASE_ID + __VU * 1000000 + __ITER;
  const r = http.get(`${BASE}/api/polls/${id}/results`, { tags: { name: 'missing' }, responseCallback: expect404 });
  check(r, { 'missing poll 404': (x) => x.status === 404 });
}

export function handleSummary(data) {
  const v = (name) => data.metrics[name].values;
  const d = v('http_req_duration{name:missing}');
  const seconds = data.state.testRunDurationMs / 1000;
  const reqs = data.metrics.http_reqs.values.count;
  const errors = v('http_req_failed{name:missing}').rate;
  const out = { tag: TAG, ids: IDS, vus: VUS, requests: reqs, rps: reqs / seconds, p95: d['p(95)'], p99: d['p(99)'], errors };
  return {
    stdout: `\nscenario-penetration ${TAG}: ${IDS || 'unique'} ids, ${VUS} VUs, ${reqs} requests, RPS ${out.rps.toFixed(0)}, ` +
      `p95 ${d['p(95)'].toFixed(1)} ms, p99 ${d['p(99)'].toFixed(1)} ms, errors ${(errors * 100).toFixed(2)} %\n`,
    [`${__ENV.K6_SUMMARY_DIR || 'results'}/penetration-${TAG}.json`]: JSON.stringify(out),
  };
}
