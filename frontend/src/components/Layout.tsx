import { useState } from 'react';
import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { useFavorites } from '../favorites';

function Logo() {
  return (
    <Link to="/" className="logo" aria-label="Е-Опитування — на головну">
      <svg viewBox="0 0 40 40" width="44" height="44" aria-hidden="true">
        <rect width="40" height="40" rx="10" fill="var(--blue-800)" />
        <rect x="9" y="22" width="5" height="9" rx="1.5" fill="var(--yellow)" />
        <rect x="17.5" y="15" width="5" height="16" rx="1.5" fill="#fff" />
        <rect x="26" y="9" width="5" height="22" rx="1.5" fill="var(--yellow)" />
      </svg>
      <span className="logo-text">
        <b>Е-Опитування</b>
        <small>Платформа голосувань у реальному часі</small>
      </span>
    </Link>
  );
}

export function Layout() {
  const { user, logout, loading } = useAuth();
  const favorites = useFavorites();
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false);
  const close = () => setMenuOpen(false);

  return (
    <div className="app">
      <div className="topbar">
        <div className="container topbar-inner">
          <span>Навчальний проєкт курсу «Інженерія високонавантажених систем»</span>
          <a href="/swagger" target="_blank" rel="noreferrer">API · Swagger</a>
        </div>
      </div>

      <header className="header">
        <div className="container header-inner">
          <Logo />
          <button type="button" className="burger" onClick={() => setMenuOpen((v) => !v)} aria-label="Меню" aria-expanded={menuOpen}>
            <span /><span /><span />
          </button>
          <div className={`header-actions ${menuOpen ? 'open' : ''}`}>
            <nav className="nav">
              <NavLink to="/" end onClick={close}>Опитування</NavLink>
              <NavLink to="/favorites" onClick={close}>
                Обране {favorites.ids.length > 0 && <span className="count">{favorites.ids.length}</span>}
              </NavLink>
              {user && <NavLink to="/my" onClick={close}>Мої опитування</NavLink>}
            </nav>
            <Link to="/polls/new" className="btn btn-yellow" onClick={close}>+ Створити опитування</Link>
            {user ? (
              <div className="user">
                <span className="avatar" aria-hidden="true">{user.username.slice(0, 1).toUpperCase()}</span>
                <span className="user-name">{user.username}</span>
                <button
                  type="button"
                  className="btn-link"
                  onClick={() => {
                    logout();
                    close();
                    navigate('/');
                  }}
                >
                  Вийти
                </button>
              </div>
            ) : (
              !loading && <Link to="/login" className="btn btn-outline" onClick={close}>Увійти</Link>
            )}
          </div>
        </div>
      </header>

      <main className="main">
        <Outlet />
      </main>

      <footer className="footer">
        <div className="container footer-inner">
          <div>
            <b>Е-Опитування</b>
            <p>Голосування в реальному часі: PostgreSQL · Redis · HAProxy · ASP.NET Core.</p>
          </div>
          <div className="footer-links">
            <Link to="/">Усі опитування</Link>
            <Link to="/favorites">Обране</Link>
            <a href="/health" target="_blank" rel="noreferrer">Стан сервісу</a>
          </div>
        </div>
      </footer>
    </div>
  );
}
