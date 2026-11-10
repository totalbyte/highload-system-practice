// Hot Shard (лаба 7, 2.3): навантаження на нові опитування, як у живому сервісі — голосують у свіжі, а не в архівні.
// Те саме навантаження запускається на стеку з різними стратегіями роутера (load-tests/hot-shard.sh):
//   Range (SHARD_RANGE_SIZE=51) — сід (id 1..50) лежить на Shard A, усе нове — на Shard B: увесь трафік в один шард;
//   Buckets — нові опитування розкладаються по обох шардах.
//
// Ітерація: 80 % — голос або зміна голосу в одне з FRESH свіжих опитувань (allowVoteChange, тож без 409), 20 % — деталі
// опитування (читання з шарду). Один VU = один користувач, тож перші голоси одного користувача не йдуть паралельно.
// Кожна відповідь несе X-Shard: затримка пишеться окремо для кожного шарду (shard_A_duration / shard_B_duration).
import { check } from 'k6';
import { Counter, Trend } from 'k6/metrics';
import { steppedScenarios, SUMMARY_TREND_STATS, summaryFor, loginUsers, createVotablePoll, jsonPost, authGet, pick }
  from './lib.js';

const plan = steppedScenarios('hit');
const shardDuration = { A: new Trend('shard_A_duration', true), B: new Trend('shard_B_duration', true) };
const shardRequests = { A: new Counter('shard_A_requests'), B: new Counter('shard_B_requests') };

// Підметрики по ступенях і для шардових метрик — так само, як lib.js робить для http_req_duration.
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

const FRESH = Number(__ENV.FRESH || 40);

export function setup() {
  const tokens = loginUsers(1, 200);
  const fresh = [];
  for (let n = 1; n <= FRESH; n++) fresh.push(createVotablePoll(tokens[n % 20], `Hot shard #${n}`, ['A', 'B', 'C', 'D']));
  return { tokens, fresh, startedAt: Date.now() };
}

function record(r) {
  const shard = r.headers['X-Shard'];
  if (shardDuration[shard]) {
    shardDuration[shard].add(r.timings.duration);
    shardRequests[shard].add(1);
  }
}

export function hit(data) {
  const poll = pick(data.fresh);
  const token = data.tokens[(__VU - 1) % data.tokens.length];
  if (Math.random() < 0.8) {
    const r = jsonPost(`/api/polls/${poll.id}/vote`, { optionId: pick(poll.options) }, token, 'vote');
    check(r, { 'vote 201/200': (x) => x.status === 201 || x.status === 200 });
    record(r);
  } else {
    const r = authGet(`/api/polls/${poll.id}`, null, 'details');
    check(r, { 'details 200': (x) => x.status === 200 });
    record(r);
  }
}

const base = summaryFor('scenario-hot-shard', plan.step);

// До таблиці lib.js — та сама розбивка по шардах: частка запитів і p95 кожного шарду на кожному ступені.
export function handleSummary(data) {
  const result = base(data);
  const steps = Object.keys(plan.scenarios).filter((s) => s !== 'warmup');
  const fmt = (v) => (v === undefined ? '-' : v.toFixed(1));
  let out = '\nper shard (share of requests, p95 / p99 ms)\nstep        shard A share  A p95   A p99   shard B share  B p95   B p99\n';
  for (const s of steps) {
    const count = (shard) => data.metrics[`shard_${shard}_requests{scenario:${s}}`]?.values.count || 0;
    const trend = (shard) => data.metrics[`shard_${shard}_duration{scenario:${s}}`]?.values || {};
    const total = count('A') + count('B');
    const share = (shard) => (total ? ((100 * count(shard)) / total).toFixed(1) : '-');
    out += `${s.padEnd(11)} ${share('A').padStart(12)} %  ${fmt(trend('A')['p(95)']).padStart(6)}  ${fmt(trend('A')['p(99)']).padStart(6)}` +
      `  ${share('B').padStart(12)} %  ${fmt(trend('B')['p(95)']).padStart(6)}  ${fmt(trend('B')['p(99)']).padStart(6)}\n`;
  }
  result.stdout += out;
  return result;
}
