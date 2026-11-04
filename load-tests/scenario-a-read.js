// Scenario A — Read-Intensive (лаба 5, 2.1): глядачі лайв-дашборду і каталогу опитувань.
// Навантаження на шар кешу (Redis) для результатів і на PostgreSQL для каталогу та деталей опитування.
//   docker compose -f docker-compose.yml -f load-tests/docker-compose.loadtest.yml run --rm k6 run scenario-a-read.js
//
// Суміш на ітерацію (закрита модель, без пауз між запитами — шукаємо межу системи, а не імітуємо темп людини):
//   60 % GET /api/polls/{id}/results — половина з них по гарячому опитуванню #1, решта по випадкових активних;
//   25 % GET /api/polls/{id}          — деталі опитування (PostgreSQL, без кешу);
//   15 % GET /api/polls?status=active  — каталог, сторінка з 20 опитувань (PostgreSQL).
import http from 'k6/http';
import { check } from 'k6';
import { BASE, steppedScenarios, SUMMARY_TREND_STATS, summaryFor, pick } from './lib.js';

const plan = steppedScenarios('read');
export const options = {
  scenarios: plan.scenarios,
  thresholds: plan.thresholds,
  summaryTrendStats: SUMMARY_TREND_STATS,
};

export function setup() {
  const r = http.get(`${BASE}/api/polls?status=active&pageSize=100`, { tags: { name: 'setup_catalog' } });
  return { active: r.json('items').map((p) => p.id), startedAt: Date.now() };
}

export function read(data) {
  const roll = Math.random();
  if (roll < 0.6) {
    const id = Math.random() < 0.5 ? 1 : pick(data.active);
    const r = http.get(`${BASE}/api/polls/${id}/results`, { tags: { name: 'results' } });
    check(r, { 'results 200': (x) => x.status === 200 });
  } else if (roll < 0.85) {
    const r = http.get(`${BASE}/api/polls/${pick(data.active)}`, { tags: { name: 'poll_details' } });
    check(r, { 'details 200': (x) => x.status === 200 });
  } else {
    const r = http.get(`${BASE}/api/polls?status=active&page=${1 + Math.floor(Math.random() * 2)}&pageSize=20`,
      { tags: { name: 'catalog' } });
    check(r, { 'catalog 200': (x) => x.status === 200 });
  }
}

export const handleSummary = summaryFor('scenario-a-read', plan.step);
