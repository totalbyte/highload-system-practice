// Scenario B — Write-Intensive (лаба 5, 2.1): голосування в гарячі опитування.
// Профіль: транзакції PostgreSQL, рядкове блокування голосу (FOR UPDATE) і лічильників options.vote_count, інвалідація
// кешу в Redis після кожного коміту (ADR 0014, 0017, 0041).
//   docker compose -f docker-compose.yml -f load-tests/docker-compose.loadtest.yml run --rm k6 run scenario-b-write.js
//
// Кожна ітерація — один POST /api/polls/{id}/vote від випадкового з 500 сід-користувачів за випадковий варіант:
//   70 % — гаряче опитування #1 (4 варіанти — 4 рядки, за які конкурують усі), 30 % — три свіжі опитування з setup().
// Усі опитування з allowVoteChange: перший голос користувача — 201, наступні — 200 (зміна або той самий варіант),
// тож 409 «вже голосував» не виникає і http_req_failed означає справжні збої.
import { check } from 'k6';
import { steppedScenarios, SUMMARY_TREND_STATS, summaryFor, loginUsers, createVotablePoll, optionIds, jsonPost, pick }
  from './lib.js';

const plan = steppedScenarios('vote');
export const options = {
  scenarios: plan.scenarios,
  thresholds: plan.thresholds,
  summaryTrendStats: SUMMARY_TREND_STATS,
  setupTimeout: '180s',
};

export function setup() {
  const tokens = loginUsers(1, 500);
  const fresh = [1, 2, 3].map((n) => createVotablePoll(tokens[0], `Load B #${n}`, ['A', 'B', 'C', 'D']));
  return { tokens, hot: { id: 1, options: optionIds(1) }, fresh };
}

export function vote(data) {
  const poll = Math.random() < 0.7 ? data.hot : pick(data.fresh);
  const r = jsonPost(`/api/polls/${poll.id}/vote`, { optionId: pick(poll.options) }, pick(data.tokens), 'vote');
  check(r, { 'vote 201/200': (x) => x.status === 201 || x.status === 200 });
}

export const handleSummary = summaryFor('scenario-b-write', plan.step);
