// Спільне для сценаріїв лаби 5: ступені навантаження, логін, підсумок по кожному ступеню.
import http from 'k6/http';
import { check, fail } from 'k6';

export const BASE = __ENV.BASE_URL || 'http://localhost:8080';
export const PASSWORD = 'Password123!';
const JSON_HEADERS = { 'Content-Type': 'application/json' };

// 201 / 200 — успіх; усе інше (зокрема 409 і 5xx) рахується в http_req_failed, тож сценарії не повинні їх
// провокувати навмисно (див. вибір опитувань у scenario-b / scenario-c).
http.setResponseCallback(http.expectedStatuses(200, 201));

/**
 * Ступеневе навантаження (2.3): warm-up, далі плато на кожному рівні VU. Кожен рівень — окремий k6-scenario з
 * constant-vus і власним startTime, тож метрики k6 має окремо по кожному ступеню (тег `scenario`).
 * Між ступенями пауза: VU попереднього ступеня встигають завершити ітерацію і не змішуються з наступним.
 * LEVELS / STEP / WARMUP можна перевизначити змінними оточення (наприклад, для швидкої перевірки скрипта).
 */
export function steppedScenarios(exec) {
  const levels = (__ENV.LEVELS || '10,25,50,100,200').split(',').map(Number);
  const step = Number(__ENV.STEP || 40);
  const warmup = Number(__ENV.WARMUP || 20);
  const gap = 5;
  const scenarios = {
    // Розігрів (2.3.1): пули з'єднань Npgsql і HAProxy, DNS, JIT-компіляція гарячих методів, кеш Redis.
    warmup: { executor: 'constant-vus', exec, vus: levels[0], duration: `${warmup}s`, gracefulStop: '3s' },
  };
  let start = warmup + gap;
  for (const vus of levels) {
    scenarios[`vus_${String(vus).padStart(3, '0')}`] = {
      executor: 'constant-vus', exec, vus, duration: `${step}s`, startTime: `${start}s`, gracefulStop: '3s',
    };
    start += step + gap;
  }
  // Порожній поріг на кожен ступінь — так k6 рахує й зберігає підметрики {scenario:...} у підсумку.
  const thresholds = {};
  for (const name of Object.keys(scenarios)) {
    thresholds[`http_req_duration{scenario:${name}}`] = ['max>=0'];
    thresholds[`http_req_failed{scenario:${name}}`] = ['rate>=0'];
    thresholds[`http_reqs{scenario:${name}}`] = ['count>=0'];
    thresholds[`iteration_duration{scenario:${name}}`] = ['max>=0'];
  }
  return { scenarios, thresholds, step, levels };
}

export const SUMMARY_TREND_STATS = ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'];

export function jsonPost(path, body, token, name) {
  const headers = token ? { ...JSON_HEADERS, Authorization: `Bearer ${token}` } : JSON_HEADERS;
  return http.post(`${BASE}${path}`, JSON.stringify(body), { headers, tags: { name } });
}

export function authPatch(path, token, name) {
  return http.patch(`${BASE}${path}`, null, { headers: { Authorization: `Bearer ${token}` }, tags: { name } });
}

export function authGet(path, token, name) {
  return http.get(`${BASE}${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {}, tags: { name } });
}

/**
 * Логін сід-користувачів у setup(): логін навмисно CPU-важкий (хешування пароля) і не є частиною сценаріїв, тож
 * його не міряємо. Пачками по 25 паралельних запитів, щоб не чекати 500 послідовних логінів.
 */
export function loginUsers(from, to) {
  const tokens = [];
  for (let n = from; n <= to; n += 25) {
    const batch = [];
    for (let k = n; k < Math.min(n + 25, to + 1); k++) {
      const email = `user${String(k).padStart(3, '0')}@example.com`;
      batch.push(['POST', `${BASE}/api/auth/login`, JSON.stringify({ email, password: PASSWORD }),
        { headers: JSON_HEADERS, tags: { name: 'setup_login' } }]);
    }
    for (const r of http.batch(batch)) {
      if (r.status !== 200) fail(`login failed: HTTP ${r.status}`);
      tokens.push(r.json('accessToken'));
    }
  }
  return tokens;
}

/** Свіже опитування з allowVoteChange: повторні голоси дають 200 (зміна), а не 409 — write-сценарій без «помилок». */
export function createVotablePoll(token, title, options) {
  const created = jsonPost('/api/polls', {
    title: `${title} ${Date.now()}`, options, endsAt: '2030-01-01T00:00:00Z', allowVoteChange: true,
  }, token, 'setup_create');
  check(created, { 'setup: poll created': (r) => r.status === 201 }) || fail(`create poll: HTTP ${created.status}`);
  const published = authPatch(`/api/polls/${created.json('id')}/publish`, token, 'setup_publish');
  published.status === 200 || fail(`publish poll: HTTP ${published.status}`);
  return { id: published.json('id'), options: published.json('options').map((o) => o.id) };
}

export function optionIds(pollId) {
  const r = http.get(`${BASE}/api/polls/${pollId}`, { tags: { name: 'setup_poll' } });
  r.status === 200 || fail(`poll ${pollId}: HTTP ${r.status}`);
  return r.json('options').map((o) => o.id);
}

export function pick(list) {
  return list[Math.floor(Math.random() * list.length)];
}

/**
 * Підсумок прогону: таблиця «ступінь → RPS, avg, p50, p95, p99, помилки» у консоль і повний JSON у results/
 * (з нього load-tests/report.py будує таблиці й графіки).
 */
export function summaryFor(name, step) {
  return (data) => {
    const rows = Object.keys(data.metrics)
      .map((k) => k.match(/^http_req_duration\{scenario:(.+)\}$/))
      .filter(Boolean)
      .map((m) => m[1])
      .sort((a, b) => (a === 'warmup' ? -1 : b === 'warmup' ? 1 : a.localeCompare(b)));
    const fmt = (v) => (v === undefined ? '-' : v.toFixed(1));
    let out = `\n${name}: per-step results (closed model, ${step}s per step)\n`;
    out += 'step        VUs   RPS     avg ms  p50 ms  p95 ms  p99 ms  max ms  errors %\n';
    for (const s of rows) {
      const d = data.metrics[`http_req_duration{scenario:${s}}`].values;
      const reqs = data.metrics[`http_reqs{scenario:${s}}`].values.count;
      const failed = data.metrics[`http_req_failed{scenario:${s}}`].values.rate;
      const vus = s === 'warmup' ? '-' : String(Number(s.slice(4)));
      const seconds = s === 'warmup' ? Number(__ENV.WARMUP || 20) : step;
      out += `${s.padEnd(11)} ${vus.padStart(4)} ${String(Math.round(reqs / seconds)).padStart(6)}  ` +
        `${fmt(d.avg).padStart(6)}  ${fmt(d.med).padStart(6)}  ${fmt(d['p(95)']).padStart(6)}  ` +
        `${fmt(d['p(99)']).padStart(6)}  ${fmt(d.max).padStart(6)}  ${(failed * 100).toFixed(2).padStart(7)}\n`;
    }
    const stamp = new Date().toISOString().replace(/[:.]/g, '-');
    const tag = __ENV.RUN_TAG ? `-${__ENV.RUN_TAG}` : '';
    // Без токенів: вони не потрібні звіту і роздувають JSON. startedAt (кінець setup) — щоб зіставити ступені з
    // ресурсами, знятими run.sh.
    const { tokens, ...setupData } = data.setup_data || {};
    const saved = { ...data, setup_data: setupData, schedule: { step, warmup: Number(__ENV.WARMUP || 20), gap: 5 } };
    return {
      stdout: out,
      [`results/${name}${tag}-${stamp}.json`]: JSON.stringify(saved, null, 1),
    };
  };
}
