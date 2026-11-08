import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import type { PollSummary } from '../api/types';
import { formatDate, phaseOf, plural, pollNumber, timeLeft, votesLabel } from '../format';
import { FavoriteButton, PhaseBadge } from './ui';

/**
 * Картка в списку, як петиція в реєстрі: номер, назва, автор, дата, лічильник голосів.
 * Лічильник — з GET /results, який майже завжди віддається з Redis (HIT), тож БД список не навантажує.
 */
export function PollCard({ poll }: { poll: PollSummary }) {
  const phase = phaseOf(poll);
  const results = useQuery({
    queryKey: ['results', poll.id],
    queryFn: () => api.getResults(poll.id),
    staleTime: 10_000,
  });

  const total = results.data?.totalVotes ?? 0;
  const leader = results.data?.options.reduce<null | (typeof results.data.options)[number]>(
    (best, o) => (!best || o.votes > best.votes ? o : best), null);
  const left = phase === 'open' ? timeLeft(poll.endsAt) : null;

  return (
    <article className="poll-card">
      <div className="poll-card-head">
        <span className="poll-number">{pollNumber(poll.id)}</span>
        <PhaseBadge phase={phase} />
        {!poll.isPublic && <span className="badge badge-private">За посиланням</span>}
        <FavoriteButton pollId={poll.id} />
      </div>

      <h3 className="poll-card-title">
        <Link to={`/polls/${poll.id}`}>{poll.title}</Link>
      </h3>

      <div className="poll-card-meta">
        <span>Автор: <b>{poll.creatorUsername}</b></span>
        <span>Оприлюднено: {formatDate(poll.createdAt)}</span>
        <span>{poll.optionsCount} {plural(poll.optionsCount, 'варіант', 'варіанти', 'варіантів')}</span>
      </div>

      <div className="poll-card-foot">
        <div className="poll-card-progress">
          <div className="progress-label">
            <span className="votes-count">{results.isPending ? '…' : votesLabel(total)}</span>
            {leader && total > 0 && (
              <span className="leader">
                Лідирує «{leader.text}» — {Math.round(leader.percentage)}%
              </span>
            )}
          </div>
          <div className="progress">
            <div className="progress-bar" style={{ width: `${leader && total > 0 ? leader.percentage : 0}%` }} />
          </div>
        </div>
        <div className="poll-card-time">
          {left ? (
            <>
              <span className="muted">Залишилось</span>
              <b>{left}</b>
            </>
          ) : (
            <>
              <span className="muted">Дата завершення</span>
              <b>{formatDate(poll.endsAt)}</b>
            </>
          )}
        </div>
      </div>
    </article>
  );
}
