import { useState, type FormEvent } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { ApiError, api } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { Breadcrumbs, ErrorBox, Spinner } from '../components/ui';

const MAX_OPTIONS = 20;

/** Значення для <input type="datetime-local"> у локальному часі. */
function toLocalInput(date: Date) {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export function CreatePollPage() {
  const { user, loading } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [options, setOptions] = useState(['', '']);
  const [endsAt, setEndsAt] = useState(() => toLocalInput(new Date(Date.now() + 7 * 86_400_000)));
  const [startsAt, setStartsAt] = useState('');
  const [isPublic, setIsPublic] = useState(true);
  const [allowVoteChange, setAllowVoteChange] = useState(false);
  const [publishNow, setPublishNow] = useState(true);

  const create = useMutation({
    mutationFn: async () => {
      const poll = await api.createPoll({
        title: title.trim(),
        description: description.trim() || undefined,
        options: options.map((o) => o.trim()).filter(Boolean),
        endsAt: new Date(endsAt).toISOString(),
        startsAt: startsAt ? new Date(startsAt).toISOString() : undefined,
        isPublic,
        allowVoteChange,
      });
      return publishNow ? api.publishPoll(poll.id) : poll;
    },
    onSuccess: (poll) => {
      queryClient.setQueryData(['poll', poll.id], poll);
      queryClient.invalidateQueries({ queryKey: ['polls'] });
      navigate(`/polls/${poll.id}`);
    },
  });

  if (loading) return <div className="container section"><Spinner /></div>;
  if (!user) return <Navigate to="/login" state={{ from: location.pathname }} replace />;

  const errors = create.error instanceof ApiError ? create.error.errors : {};
  const fe = (prefix: string) =>
    Object.entries(errors).filter(([k]) => k.toLowerCase().startsWith(prefix.toLowerCase())).flatMap(([, v]) => v)[0];

  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate();
  };

  return (
    <div className="container section">
      <Breadcrumbs items={[{ to: '/', label: 'Опитування' }, { label: 'Нове опитування' }]} />
      <form className="card form-card" onSubmit={submit}>
        <h1>Нове опитування</h1>
        <p className="muted">Сформулюйте питання і варіанти відповіді. Після публікації змінити їх буде неможливо.</p>

        {create.isError && Object.keys(errors).length === 0 && <ErrorBox error={create.error} />}

        <label className="field">
          <span>Питання *</span>
          <input required maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Наприклад: Який формат захисту лаби зручніший?" />
          <small className={fe('title') ? 'field-error' : ''}>{fe('title') ?? `${title.length} / 200`}</small>
        </label>

        <label className="field">
          <span>Опис</span>
          <textarea rows={4} maxLength={2000} value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Контекст, умови, посилання…" />
          <small className={fe('description') ? 'field-error' : ''}>{fe('description') ?? `${description.length} / 2000`}</small>
        </label>

        <fieldset className="field">
          <legend>Варіанти відповіді * <small>(від 2 до {MAX_OPTIONS})</small></legend>
          {options.map((o, i) => (
            <div className="option-input" key={i}>
              <span className="option-index">{i + 1}</span>
              <input
                required
                maxLength={200}
                value={o}
                onChange={(e) => setOptions(options.map((x, j) => (j === i ? e.target.value : x)))}
                placeholder={`Варіант ${i + 1}`}
              />
              <button
                type="button"
                className="btn-icon"
                disabled={options.length <= 2}
                onClick={() => setOptions(options.filter((_, j) => j !== i))}
                aria-label={`Видалити варіант ${i + 1}`}
              >
                ×
              </button>
            </div>
          ))}
          {fe('options') && <small className="field-error">{fe('options')}</small>}
          <button type="button" className="btn btn-outline" disabled={options.length >= MAX_OPTIONS} onClick={() => setOptions([...options, ''])}>
            + Додати варіант
          </button>
        </fieldset>

        <div className="field-row">
          <label className="field">
            <span>Початок голосування</span>
            <input type="datetime-local" value={startsAt} onChange={(e) => setStartsAt(e.target.value)} />
            <small className={fe('startsAt') ? 'field-error' : ''}>{fe('startsAt') ?? 'Порожньо — одразу після публікації'}</small>
          </label>
          <label className="field">
            <span>Завершення *</span>
            <input type="datetime-local" required value={endsAt} onChange={(e) => setEndsAt(e.target.value)} />
            {fe('endsAt') && <small className="field-error">{fe('endsAt')}</small>}
          </label>
        </div>

        <div className="checks">
          <label className="check">
            <input type="checkbox" checked={isPublic} onChange={(e) => setIsPublic(e.target.checked)} />
            <span><b>Публічне</b> — показувати в загальному списку (інакше — лише за посиланням)</span>
          </label>
          <label className="check">
            <input type="checkbox" checked={allowVoteChange} onChange={(e) => setAllowVoteChange(e.target.checked)} />
            <span><b>Дозволити змінювати голос</b> до завершення опитування</span>
          </label>
          <label className="check">
            <input type="checkbox" checked={publishNow} onChange={(e) => setPublishNow(e.target.checked)} />
            <span><b>Опублікувати одразу</b> (інакше збережеться чернеткою)</span>
          </label>
        </div>

        <div className="form-actions">
          <Link to="/" className="btn btn-ghost-dark">Скасувати</Link>
          <button type="submit" className="btn btn-primary btn-lg" disabled={create.isPending}>
            {create.isPending ? 'Зберігаємо…' : publishNow ? 'Створити й опублікувати' : 'Зберегти чернетку'}
          </button>
        </div>
      </form>
    </div>
  );
}
