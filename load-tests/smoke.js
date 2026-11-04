// Пробний прогін контуру (лаба 5, етап 1): 5 VU × 10 с на GET /health і GET /results через балансувальник.
// Перевіряє, що k6 бачить lb:8080, обидва інстанси відповідають і заголовки X-Instance-ID / X-Cache доходять.
//   docker compose -f docker-compose.yml -f load-tests/docker-compose.loadtest.yml run --rm k6 run smoke.js
import http from 'k6/http';
import { check } from 'k6';

const BASE = __ENV.BASE_URL || 'http://localhost:8080';

export const options = {
  vus: 5,
  duration: '10s',
  thresholds: {
    http_req_failed: ['rate==0'],
    // Без порогу на checks k6 завершується успішно, навіть якщо заголовки X-Instance-ID / X-Cache не прийшли.
    checks: ['rate==1'],
  },
};

export default function () {
  const health = http.get(`${BASE}/health`, { tags: { name: 'health' } });
  check(health, {
    'health 200': (r) => r.status === 200,
    'has X-Instance-ID': (r) => !!r.headers['X-Instance-Id'],
  });

  const results = http.get(`${BASE}/api/polls/1/results`, { tags: { name: 'results' } });
  check(results, {
    'results 200': (r) => r.status === 200,
    'has X-Cache': (r) => !!r.headers['X-Cache'],
  });
}
