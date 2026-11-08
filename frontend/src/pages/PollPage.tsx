import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { ApiError, api } from '../api/client';
import type { PollDetails } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { Breadcrumbs, ErrorBox, FavoriteButton, PhaseBadge, ServedByBadge, Spinner } from '../components/ui';
import { formatDateTime, formatTime, phaseOf, plural, pollNumber, timeLeft, votesLabel } from '../format';

export function PollPage() {
  const id = Number(useParams().id);
  if (!Number.isInteger(id)) {
    return (
      <div className="container section">
        <Breadcrumbs items={[{ label: 'Опитування' }]} />
        <div className="card narrow center">
          <h1>Опитування не знайдено</h1>
          <p className="muted">Можливо, його видалили або це чужа чернетка.</p>
          <Link to="/" className="btn btn-primary">До списку опитувань</Link>
        </div>
      </div>
    );
  }
  const poll = useQuery({ queryKey: ['poll', id], queryFn: () => api.getPoll(id), enabled: Number.isInteger(id) });

  if (poll.isPending) return <div className="container section"><Spinner /></div>;
  if (poll.isError) {
    const notFound = poll.error instanceof ApiError && poll.error.status === 404;
    return (
      <div className="container section">
        <Breadcrumbs items={[{ label: 'Опитування' }]} />
        {notFound ? (
          <div className="card narrow center">
            <h1>Опитування не знайдено</h1>
            <p className="muted">Можливо, його видалили або це чужа чернетка.</p>
            <Link to="/" className="btn btn-primary">До списку опитувань</Link>
          </div>
        ) : (
          <ErrorBox error={poll.error} />
        )}
      </div>
    );
  }
  return <PollView poll={poll.data} />;
}

function PollView({ poll }: { poll: PollDetails }) {
  const { user } = useAuth();
  const location = useLocation();
  const queryClient = useQueryClient();
  const phase = phaseOf(poll);
  const isAuthor = user?.id === poll.creatorId;

  // Поки триває голосування, результати оновлюються кожні 5 с (у фоновій вкладці — ні).
  const results = useQuery({
    queryKey: ['results', poll.id],
    queryFn: () => api.getResults(poll.id),
    refetchInterval: phase === 'open' ? 5_000 : false,
  });
  const myVote = useQuery({
    queryKey: ['myVote', poll.id],
    queryFn: () => api.getMyVote(poll.id),
    enabled: !!user,
  });

  const [selected, setSelected] = useState<number | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const vote = useMutation({
    mutationFn: (optionId: number) => api.vote(poll.id, optionId),
    onSuccess: (v) => {
      queryClient.setQueryData(['myVote', poll.id], v);
      queryClient.invalidateQueries({ queryKey: ['results', poll.id] });
      setSelected(null);
      setNotice('Дякуємо! Ваш голос враховано.');
    },
  });

  const votedFor = myVote.data?.optionId ?? null;
  const canVote = !!user && phase === 'open' && (votedFor === null || poll.allowVoteChange);
  const choice = selected ?? votedFor;
  const total = results.data?.totalVotes ?? 0;
  const byOption = new Map(results.data?.options.map((o) => [o.id, o]) ?? []);
  const maxVotes = Math.max(0, ...(results.data?.options.map((o) => o.votes) ?? [0]));
  const left = phase === 'open' ? timeLeft(poll.endsAt) : null;

  return (
    <div className="container section">
      <Breadcrumbs items={[{ to: '/', label: 'Опитування' }, { label: pollNumber(poll.id) }]} />

      <div className="poll-layout">
        <article className="card poll-main">
          <div className="poll-head">
            <span className="poll-number">Опитування {pollNumber(poll.id)}</span>
            <PhaseBadge phase={phase} />
            {!poll.isPublic && <span className="badge badge-private">Доступне за посиланням</span>}
            {poll.allowVoteChange && <span className="badge badge-soft">Голос можна змінити</span>}
          </div>
          <h1 className="poll-title">{poll.title}</h1>

          <dl className="poll-meta">
            <div><dt>Автор (ініціатор)</dt><dd>{poll.creatorUsername}</dd></div>
            <div><dt>Дата оприлюднення</dt><dd>{formatDateTime(poll.createdAt)}</dd></div>
            {poll.startsAt && <div><dt>Початок голосування</dt><dd>{formatDateTime(poll.startsAt)}</dd></div>}
            <div><dt>Завершення</dt><dd>{formatDateTime(poll.endsAt)}</dd></div>
          </dl>

          {poll.description && <div className="poll-description">{poll.description}</div>}

          <h2 className="h2">{canVote ? 'Оберіть варіант відповіді' : 'Результати голосування'}</h2>

          {notice && <div className="alert alert-success" role="status">{notice}</div>}
          {vote.isError && <ErrorBox error={vote.error} />}
          {results.isError && <ErrorBox error={results.error} />}

          <div className="options" role={canVote ? 'radiogroup' : undefined}>
            {[...poll.options].sort((a, b) => a.position - b.position).map((o) => {
              const r = byOption.get(o.id);
              const pct = r?.percentage ?? 0;
              const mine = votedFor === o.id;
              const leading = total > 0 && r?.votes === maxVotes;
              return (
                <label
                  key={o.id}
                  className={['option', canVote && 'option-selectable', choice === o.id && canVote && 'option-checked', mine && 'option-mine', leading && 'option-leading']
                    .filter(Boolean).join(' ')}
                >
                  {canVote && (
                    <input
                      type="radio"
                      name="option"
                      value={o.id}
                      checked={choice === o.id}
                      onChange={() => {
                        setSelected(o.id);
                        setNotice(null);
                      }}
                    />
                  )}
                  <div className="option-body">
                    <div className="option-row">
                      <span className="option-text">
                        {o.text}
                        {mine && <span className="mine-tag">Ваш вибір</span>}
                      </span>
                      <span className="option-pct">{Math.round(pct * 10) / 10}%</span>
                    </div>
                    <div className="progress progress-thin">
                      <div className="progress-bar" style={{ width: `${pct}%` }} />
                    </div>
                    <span className="option-votes">{votesLabel(r?.votes ?? 0)}</span>
                  </div>
                </label>
              );
            })}
          </div>

          {canVote && (
            <div className="vote-actions">
              <button
                type="button"
                className="btn btn-primary btn-lg"
                disabled={choice === null || choice === votedFor || vote.isPending}
                onClick={() => choice !== null && vote.mutate(choice)}
              >
                {vote.isPending ? 'Надсилаємо…' : votedFor === null ? 'Проголосувати' : 'Змінити голос'}
              </button>
              {votedFor !== null && <span className="muted">Ви вже голосували — можна обрати інший варіант.</span>}
            </div>
          )}

          {results.data && (
            <div className="results-foot">
              <span>Результати станом на {formatTime(results.data.generatedAt)}</span>
              <ServedByBadge servedBy={results.data.servedBy} />
            </div>
          )}
        </article>

        <aside className="poll-side">
          <div className="card side-card">
            <span className="side-label">Проголосувало</span>
            <span className="side-total">{results.isPending ? '…' : total.toLocaleString('uk-UA')}</span>
            <span className="muted">{plural(total, 'голос', 'голоси', 'голосів')}</span>
            <div className="side-divider" />
            {left ? (
              <p className="side-time">До завершення: <b>{left}</b></p>
            ) : (
              <p className="side-time"><PhaseBadge phase={phase} /></p>
            )}

            {!user && phase === 'open' && (
              <Link to="/login" state={{ from: location.pathname }} className="btn btn-primary btn-block">
                Увійдіть, щоб проголосувати
              </Link>
            )}
            {user && phase === 'open' && votedFor !== null && !poll.allowVoteChange && (
              <p className="side-voted">✓ Ви вже проголосували в цьому опитуванні</p>
            )}
            {phase === 'scheduled' && poll.startsAt && (
              <p className="muted">Голосування розпочнеться {formatDateTime(poll.startsAt)}</p>
            )}

            <FavoriteButton pollId={poll.id} withText />
          </div>

          {isAuthor && <AuthorActions poll={poll} />}
        </aside>
      </div>
    </div>
  );
}

function AuthorActions({ poll }: { poll: PollDetails }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const refresh = (updated: PollDetails) => {
    queryClient.setQueryData(['poll', poll.id], updated);
    queryClient.invalidateQueries({ queryKey: ['results', poll.id] });
    queryClient.invalidateQueries({ queryKey: ['polls'] });
  };

  const publish = useMutation({ mutationFn: () => api.publishPoll(poll.id), onSuccess: refresh });
  const close = useMutation({ mutationFn: () => api.closePoll(poll.id), onSuccess: refresh });
  const remove = useMutation({
    mutationFn: () => api.deletePoll(poll.id),
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: ['poll', poll.id] });
      queryClient.invalidateQueries({ queryKey: ['polls'] });
      navigate('/my');
    },
  });
  const error = publish.error ?? close.error ?? remove.error;

  return (
    <div className="card side-card author-card">
      <span className="side-label">Керування (ви автор)</span>
      {error && <ErrorBox error={error} />}
      {poll.status === 'draft' && (
        <>
          <p className="muted">Чернетку бачите лише ви. Після публікації почнеться голосування.</p>
          <button type="button" className="btn btn-primary btn-block" disabled={publish.isPending} onClick={() => publish.mutate()}>
            Опублікувати
          </button>
          <button
            type="button"
            className="btn btn-danger-outline btn-block"
            disabled={remove.isPending}
            onClick={() => window.confirm('Видалити чернетку безповоротно?') && remove.mutate()}
          >
            Видалити чернетку
          </button>
        </>
      )}
      {poll.status === 'active' && (
        <button
          type="button"
          className="btn btn-outline btn-block"
          disabled={close.isPending}
          onClick={() => window.confirm('Завершити голосування достроково?') && close.mutate()}
        >
          Завершити достроково
        </button>
      )}
      {poll.status === 'closed' && <p className="muted">Голосування завершено. Результати зафіксовано.</p>}
    </div>
  );
}
