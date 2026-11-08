import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import type { ServedBy } from '../api/types';
import { useFavorites } from '../favorites';
import { phaseLabel, type Phase } from '../format';

export function PhaseBadge({ phase }: { phase: Phase }) {
  return <span className={`badge badge-${phase}`}>{phaseLabel[phase]}</span>;
}

export function FavoriteButton({ pollId, withText = false }: { pollId: number; withText?: boolean }) {
  const favorites = useFavorites();
  const active = favorites.has(pollId);
  const label = active ? 'Прибрати з обраного' : 'Додати в обране';
  return (
    <button
      type="button"
      className={`fav ${active ? 'fav-on' : ''} ${withText ? 'fav-wide' : ''}`}
      onClick={(e) => {
        e.preventDefault();
        favorites.toggle(pollId);
      }}
      aria-pressed={active}
      title={label}
      aria-label={label}
    >
      <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
        <path d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z" />
      </svg>
      {withText && <span>{active ? 'В обраному' : 'В обране'}</span>}
    </button>
  );
}

export function Spinner({ label = 'Завантаження…' }: { label?: string }) {
  return (
    <div className="spinner-wrap" role="status">
      <span className="spinner" />
      <span>{label}</span>
    </div>
  );
}

export function ErrorBox({ error, children }: { error?: unknown; children?: ReactNode }) {
  const message = error instanceof Error ? error.message : children;
  return (
    <div className="alert alert-error" role="alert">
      {message}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <svg viewBox="0 0 48 48" width="56" height="56" aria-hidden="true">
        <rect x="8" y="6" width="32" height="36" rx="4" fill="none" stroke="currentColor" strokeWidth="2.5" />
        <path d="M16 18h16M16 25h16M16 32h9" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" />
      </svg>
      <h3>{title}</h3>
      {children}
    </div>
  );
}

export function Pagination({ page, pageSize, total, onChange }: {
  page: number; pageSize: number; total: number; onChange: (page: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (pages <= 1) return null;

  // 1 … 4 5 [6] 7 8 … 20
  const shown = new Set([1, pages, page - 2, page - 1, page, page + 1, page + 2].filter((p) => p >= 1 && p <= pages));
  const list = [...shown].sort((a, b) => a - b);

  return (
    <nav className="pagination" aria-label="Сторінки">
      <button type="button" disabled={page <= 1} onClick={() => onChange(page - 1)} aria-label="Попередня">‹</button>
      {list.map((p, i) => (
        <span key={p} className="pagination-group">
          {i > 0 && list[i - 1] !== p - 1 && <span className="pagination-gap">…</span>}
          <button type="button" className={p === page ? 'current' : ''} onClick={() => onChange(p)} aria-current={p === page}>
            {p}
          </button>
        </span>
      ))}
      <button type="button" disabled={page >= pages} onClick={() => onChange(page + 1)} aria-label="Наступна">›</button>
    </nav>
  );
}

/** Технічна плашка: який backend відповів і чи прийшли результати з Redis (корисно на захисті лаб 3–4). */
export function ServedByBadge({ servedBy }: { servedBy: ServedBy }) {
  if (!servedBy.instance && !servedBy.cache) return null;
  const cache = servedBy.cache?.toUpperCase();
  return (
    <div className="served-by" title="Заголовки відповіді X-Instance-ID та X-Cache">
      {servedBy.instance && (
        <span>
          вузол <code>{servedBy.instance}</code>
        </span>
      )}
      {cache && (
        <span>
          кеш <code className={`cache-${cache.toLowerCase()}`}>{cache}</code>
        </span>
      )}
    </div>
  );
}

export function Breadcrumbs({ items }: { items: { to?: string; label: string }[] }) {
  return (
    <nav className="breadcrumbs" aria-label="Навігація">
      <Link to="/">Головна</Link>
      {items.map((item) => (
        <span key={item.label}>
          <span className="sep">/</span>
          {item.to ? <Link to={item.to}>{item.label}</Link> : <span>{item.label}</span>}
        </span>
      ))}
    </nav>
  );
}
