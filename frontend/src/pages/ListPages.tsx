import { useState } from 'react';
import { keepPreviousData, useQueries, useQuery } from '@tanstack/react-query';
import { Link, Navigate, useLocation } from 'react-router-dom';
import { ApiError, api } from '../api/client';
import type { PollDetails } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { PollCard } from '../components/PollCard';
import { Breadcrumbs, EmptyState, ErrorBox, Pagination, Spinner } from '../components/ui';
import { useFavorites } from '../favorites';

const PAGE_SIZE = 10;

/** Мої опитування — включно з чернетками: автор бачить у списку всі свої (ADR 0003). */
export function MyPollsPage() {
  const { user, loading } = useAuth();
  const location = useLocation();
  const [page, setPage] = useState(1);

  const query = { creatorId: user?.id, page, pageSize: PAGE_SIZE };
  const list = useQuery({
    queryKey: ['polls', query],
    queryFn: () => api.listPolls(query),
    enabled: !!user,
    placeholderData: keepPreviousData,
  });

  if (loading) return <div className="container section"><Spinner /></div>;
  if (!user) return <Navigate to="/login" state={{ from: location.pathname }} replace />;

  return (
    <div className="container section">
      <Breadcrumbs items={[{ label: 'Мої опитування' }]} />
      <div className="page-head">
        <h1>Мої опитування</h1>
        <Link to="/polls/new" className="btn btn-primary">+ Створити</Link>
      </div>
      {list.isPending && <Spinner />}
      {list.isError && <ErrorBox error={list.error} />}
      {list.data?.items.length === 0 && (
        <EmptyState title="Ви ще не створили жодного опитування">
          <Link to="/polls/new" className="btn btn-primary">Створити перше</Link>
        </EmptyState>
      )}
      <div className="poll-list">
        {list.data?.items.map((p) => <PollCard key={p.id} poll={p} />)}
      </div>
      {list.data && <Pagination page={page} pageSize={PAGE_SIZE} total={list.data.totalCount} onChange={setPage} />}
    </div>
  );
}

/** Обране — id з localStorage, кожне опитування підвантажується окремо (GET /api/polls/{id}). */
export function FavoritesPage() {
  const favorites = useFavorites();
  const polls = useQueries({
    queries: favorites.ids.map((id) => ({
      queryKey: ['poll', id],
      queryFn: () => api.getPoll(id),
      retry: (count: number, e: Error) => !(e instanceof ApiError && e.status === 404) && count < 2,
    })),
  });

  return (
    <div className="container section">
      <Breadcrumbs items={[{ label: 'Обране' }]} />
      <div className="page-head">
        <h1>Обране</h1>
        <span className="muted">Зберігається в цьому браузері</span>
      </div>
      {favorites.ids.length === 0 && (
        <EmptyState title="Список обраного порожній">
          <p>Натисніть ☆ на картці опитування, щоб стежити за ним тут.</p>
          <Link to="/" className="btn btn-primary">До опитувань</Link>
        </EmptyState>
      )}
      <div className="poll-list">
        {favorites.ids.map((id, i) => {
          const q = polls[i];
          if (!q || q.isPending) return <div key={id} className="poll-card skeleton" />;
          if (q.isError) {
            return (
              <div key={id} className="poll-card poll-card-gone">
                <span>Опитування №{id} недоступне — {q.error.message}</span>
                <button type="button" className="btn-link" onClick={() => favorites.remove(id)}>Прибрати</button>
              </div>
            );
          }
          return <PollCard key={id} poll={toSummary(q.data)} />;
        })}
      </div>
    </div>
  );
}

const toSummary = (p: PollDetails) => ({ ...p, optionsCount: p.options.length });

export function NotFoundPage() {
  return (
    <div className="container section">
      <div className="card narrow center">
        <h1>404</h1>
        <p className="muted">Такої сторінки немає.</p>
        <Link to="/" className="btn btn-primary">На головну</Link>
      </div>
    </div>
  );
}
