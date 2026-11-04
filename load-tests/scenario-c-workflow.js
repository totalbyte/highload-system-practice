// Scenario C — Complex Workflow (лаба 5, 2.1): наскрізний бізнес-сценарій користувача.
// Послідовне читання → рішення → запис → читання підсумку, плюс повний життєвий цикл опитування в частині ітерацій.
//   docker compose -f docker-compose.yml -f load-tests/docker-compose.loadtest.yml run --rm k6 run scenario-c-workflow.js
//
// Ітерація (один VU = один користувач зі своїм токеном):
//   1. GET  /api/polls?status=active      — каталог;
//   2. GET  /api/polls/{id}               — деталі опитування, з якого обирається варіант;
//   3. POST /api/polls/{id}/vote          — голос (опитування з allowVoteChange → 201 / 200);
//   4. GET  /api/polls/{id}/results       — підсумок після голосу;
//   5. у 20 % ітерацій — автор: POST /api/polls → PATCH publish → GET results → PATCH close → GET results (closed).
// Між кроками — пауза 100–300 мс («людина читає»), тож метрики показують і latency кожного кроку, і тривалість усього
// сценарію (iteration_duration). Ця пауза не входить у http_req_duration.
import { check, sleep, group, fail } from 'k6';
import { steppedScenarios, SUMMARY_TREND_STATS, summaryFor, loginUsers, createVotablePoll, optionIds, jsonPost,
  authGet, authPatch, pick } from './lib.js';

const plan = steppedScenarios('workflow');
export const options = {
  scenarios: plan.scenarios,
  thresholds: plan.thresholds,
  summaryTrendStats: SUMMARY_TREND_STATS,
  setupTimeout: '180s',
};

// Один VU = один користувач, тож користувачів потрібно не менше, ніж VU на найбільшому ступені. Сід за замовчуванням —
// 500; прогін до 800 VU піднімає стек із SEED_USERS=800 і передає USERS=800 (series.sh).
const USERS = Number(__ENV.USERS || 500);

export function setup() {
  const maxVus = Math.max(...plan.levels);
  if (maxVus > USERS) fail(`${maxVus} VUs need ${maxVus} distinct users, only ${USERS}: set USERS and SEED_USERS`);
  const tokens = loginUsers(1, USERS);
  const polls = [1, 2, 3, 4, 5].map((n) => createVotablePoll(tokens[0], `Load C #${n}`, ['A', 'B', 'C']));
  return { tokens, polls: [{ id: 1, options: optionIds(1) }, ...polls], startedAt: Date.now() };
}

function think() {
  sleep(0.1 + Math.random() * 0.2);
}

export function workflow(data) {
  // Свій користувач на VU: так зміни голосу одного користувача не перетинаються між VU.
  const token = data.tokens[(__VU - 1) % data.tokens.length];

  group('voter', () => {
    check(authGet('/api/polls?status=active&pageSize=10', token, 'catalog'), { 'catalog 200': (r) => r.status === 200 });
    think();
    const poll = pick(data.polls);
    const details = authGet(`/api/polls/${poll.id}`, token, 'poll_details');
    check(details, { 'details 200': (r) => r.status === 200 });
    think();
    const voted = jsonPost(`/api/polls/${poll.id}/vote`, { optionId: pick(poll.options) }, token, 'vote');
    check(voted, { 'vote 201/200': (r) => r.status === 201 || r.status === 200 });
    think();
    check(authGet(`/api/polls/${poll.id}/results`, token, 'results'), { 'results 200': (r) => r.status === 200 });
  });

  if (Math.random() < 0.2) {
    group('author', () => {
      think();
      const created = jsonPost('/api/polls', {
        title: `Workflow ${__VU}-${__ITER}`, options: ['Так', 'Ні', 'Не знаю'], endsAt: '2030-01-01T00:00:00Z',
      }, token, 'create_poll');
      if (!check(created, { 'create 201': (r) => r.status === 201 })) return;
      const id = created.json('id');
      check(authPatch(`/api/polls/${id}/publish`, token, 'publish'), { 'publish 200': (r) => r.status === 200 });
      check(authGet(`/api/polls/${id}/results`, token, 'results'), { 'results 200': (r) => r.status === 200 });
      think();
      check(authPatch(`/api/polls/${id}/close`, token, 'close'), { 'close 200': (r) => r.status === 200 });
      check(authGet(`/api/polls/${id}/results`, token, 'results'), { 'final results 200': (r) => r.status === 200 });
    });
  }
}

export const handleSummary = summaryFor('scenario-c-workflow', plan.step);
