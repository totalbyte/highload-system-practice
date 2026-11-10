// Single Node проти шардів (лаба 7, 2.6): одне навантаження, три режими (MODE), стек з SHARD_COUNT=1 або 2.
//   write   — shard-local запис: голос або зміна голосу в одне з FRESH свіжих опитувань (Primary шарду опитування);
//   read    — shard-local читання: деталі одного зі свіжих опитувань (репліка шарду опитування);
//   catalog — Cross-Shard fan-out: каталог GET /api/polls?status=active (усі шарди паралельно, злиття на backend).
// Свіжі опитування з allowVoteChange, тож повторний голос — 200, а не 409. Один VU = один користувач.
// Кожна відповідь несе X-Shard: затримка і кількість запитів пишуться окремо для кожного шарду.
//   docker compose -f docker-compose.yml -f load-tests/docker-compose.loadtest-shards.yml run --rm -e MODE=read k6 run scenario-shards.js
import { check } from 'k6';
import { Counter, Trend } from 'k6/metrics';
import { steppedScenarios, SUMMARY_TREND_STATS, summaryFor, loginUsers, createVotablePoll, jsonPost, authGet, pick }
  from './lib.js';

const MODE = __ENV.MODE || 'write';
const FRESH = Number(__ENV.FRESH || 40);
const plan = steppedScenarios('hit');

const shardDuration = { A: new Trend('shard_A_duration', true), B: new Trend('shard_B_duration', true) };
const shardRequests = { A: new Counter('shard_A_requests'), B: new Counter('shard_B_requests') };
const thresholds = { ...plan.thresholds };
for (const scenario of Object.keys(plan.scenarios)) {
  for (const shard of ['A', 'B']) {
    thresholds[`shard_${shard}_duration{scenario:${scenario}}`] = ['max>=0'];
    thresholds[`shard_${shard}_requests{scenario:${scenario}}`] = ['count>=0'];
  }
}

export const options = {
  scenarios: plan.scenarios,
  thresholds,
  summaryTrendStats: SUMMARY_TREND_STATS,
  setupTimeout: '180s',
};

export function setup() {
  const tokens = loginUsers(1, 200);
  const fresh = [];
  for (let n = 1; n <= FRESH; n++) fresh.push(createVotablePoll(tokens[n % 20], `Shards ${MODE} #${n}`, ['A', 'B', 'C', 'D']));
  return { tokens, fresh, startedAt: Date.now() };
}

function record(r) {
  // Каталог торкається всіх шардів ("A,B") — його рахуємо окремо не по шардах, а загальним http_req_duration.
  const shard = r.headers['X-Shard'];
  if (shardDuration[shard]) {
    shardDuration[shard].add(r.timings.duration);
    shardRequests[shard].add(1);
  }
}

export function hit(data) {
  if (MODE === 'catalog') {
    const r = authGet('/api/polls?status=active&pageSize=20', null, 'catalog');
    check(r, { 'catalog 200': (x) => x.status === 200 });
    return;
  }
  const poll = pick(data.fresh);
  if (MODE === 'read') {
    const r = authGet(`/api/polls/${poll.id}`, null, 'details');
    check(r, { 'details 200': (x) => x.status === 200 });
    record(r);
    return;
  }
  const token = data.tokens[(__VU - 1) % data.tokens.length];
  const r = jsonPost(`/api/polls/${poll.id}/vote`, { optionId: pick(poll.options) }, token, 'vote');
  check(r, { 'vote 201/200': (x) => x.status === 201 || x.status === 200 });
  record(r);
}

export const handleSummary = summaryFor(`scenario-shards-${MODE}`, plan.step);
