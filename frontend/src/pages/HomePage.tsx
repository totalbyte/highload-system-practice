import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { Link, useSearchParams } from 'react-router-dom';
import { api } from '../api/client';
import type { PollStatus } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { PollCard } from '../components/PollCard';
import { EmptyState, ErrorBox, Pagination, Spinner } from '../components/ui';
import { votesLabel } from '../format';

const PAGE_SIZE = 10;

const tabs: { key: string; label: string; status?: PollStatus }[] = [
  { key: 'active', label: 'Триває голосування', status: 'active' },
  { key: 'closed', label: 'Завершені', status: 'closed' },
  { key: 'all', label: 'Усі' },
];

function Hero() {
  const { user } = useAuth();
  // Скільки голосів зараз у «гарячому» опитуванні #1 (seed для навантажувальних тестів) — жива цифра на банері.
  const active = useQuery({ queryKey: ['polls', { status: 'active', page: 1, pageSize: 1 }], queryFn: () => api.listPolls({ status: 'active', pageSize: 1 }) });
  const closed = useQuery({ queryKey: ['polls', { status: 'closed', page: 1, pageSize: 1 }], queryFn: () => api.listPolls({ status: 'closed', pageSize: 1 }) });
  const hot = useQuery({ queryKey: ['results', 1], queryFn: () => api.getResults(1), retry: false, refetchInterval: 10_000 });

  return (
    <section className="hero">
      <div className="container hero-inner">
        <div className="hero-text">
          <h1>Опитування</h1>
          <p>
            Створюйте опитування, збирайте голоси та стежте за результатами в реальному часі.
            Кожен зареєстрований користувач має один голос у кожному опитуванні.
          </p>
          <div className="hero-actions">
            <Link to="/polls/new" className="btn btn-yellow btn-lg">Створити опитування</Link>
            {!user && <Link to="/register" className="btn btn-ghost btn-lg">Зареєструватися</Link>}
          </div>
        </div>
        <dl className="hero-stats">
          <div>
            <dt>Триває голосування</dt>
            <dd>{active.data?.totalCount ?? '—'}</dd>
          </div>
          <div>
            <dt>Завершено</dt>
            <dd>{closed.data?.totalCount ?? '—'}</dd>
          </div>
          {hot.data && (
            <div className="hero-hot">
              <dt>Найактивніше: «{hot.data.title}»</dt>
              <dd>{votesLabel(hot.data.totalVotes)}</dd>
            </div>
          )}
        </dl>
      </div>
    </section>
  );
}

export function HomePage() {
  const [params, setParams] = useSearchParams();
  const tab = tabs.find((t) => t.key === params.get('tab')) ?? tabs[0];
  const page = Math.max(1, Number(params.get('page')) || 1);

  const query = { status: tab.status, page, pageSize: PAGE_SIZE };
  const list = useQuery({
    queryKey: ['polls', query],
    queryFn: () => api.listPolls(query),
    placeholderData: keepPreviousData,
  });

  const go = (next: { tab?: string; page?: number }) => {
    const p = new URLSearchParams(params);
    if (next.tab) {
      p.set('tab', next.tab);
      p.delete('page');
    }
    if (next.page) p.set('page', String(next.page));
    setParams(p);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  return (
    <>
      <Hero />
      <div className="container section">
        <div className="tabs" role="tablist">
          {tabs.map((t) => (
            <button
              key={t.key}
              type="button"
              role="tab"
              aria-selected={t.key === tab.key}
              className={t.key === tab.key ? 'tab active' : 'tab'}
              onClick={() => go({ tab: t.key })}
            >
              {t.label}
              {t.key === tab.key && list.data && <span className="tab-count">{list.data.totalCount}</span>}
            </button>
          ))}
        </div>

        {list.isPending && <Spinner />}
        {list.isError && <ErrorBox error={list.error} />}
        {list.data && list.data.items.length === 0 && (
          <EmptyState title="Тут поки порожньо">
            <p>Станьте першим — <Link to="/polls/new">створіть опитування</Link>.</p>
          </EmptyState>
        )}
        {list.data && (
          <div className={`poll-list ${list.isPlaceholderData ? 'is-loading' : ''}`}>
            {list.data.items.map((p) => <PollCard key={p.id} poll={p} />)}
          </div>
        )}
        {list.data && (
          <Pagination page={page} pageSize={PAGE_SIZE} total={list.data.totalCount} onChange={(p) => go({ page: p })} />
        )}
      </div>
    </>
  );
}
