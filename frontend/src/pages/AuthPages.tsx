import { useState, type FormEvent } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { ApiError, api } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { ErrorBox } from '../components/ui';

function fieldError(error: unknown, field: string) {
  if (!(error instanceof ApiError)) return null;
  const key = Object.keys(error.errors).find((k) => k.toLowerCase() === field.toLowerCase());
  return key ? error.errors[key][0] : null;
}

function useRedirectBack() {
  const navigate = useNavigate();
  const from = (useLocation().state as { from?: string } | null)?.from ?? '/';
  return () => navigate(from, { replace: true });
}

export function LoginPage() {
  const { login } = useAuth();
  const back = useRedirectBack();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(email, password);
      back();
    } catch (err) {
      setError(err instanceof ApiError && err.status === 401 ? new Error('Невірна пошта або пароль.') : err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="container section">
      <form className="card auth-card" onSubmit={submit}>
        <h1>Вхід</h1>
        <p className="muted">Увійдіть, щоб голосувати та створювати опитування.</p>
        {!!error && <ErrorBox error={error} />}
        <label className="field">
          <span>Електронна пошта</span>
          <input type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label className="field">
          <span>Пароль</span>
          <input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        <button type="submit" className="btn btn-primary btn-block btn-lg" disabled={busy}>
          {busy ? 'Входимо…' : 'Увійти'}
        </button>
        <p className="auth-switch">
          Немає акаунта? <Link to="/register">Зареєструватися</Link>
        </p>
        <p className="hint">
          Демо-акаунти: <code>user001@example.com</code> … <code>user500@example.com</code>, пароль <code>Password123!</code>
        </p>
      </form>
    </div>
  );
}

export function RegisterPage() {
  const { login } = useAuth();
  const back = useRedirectBack();
  const [form, setForm] = useState({ username: '', email: '', password: '' });
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.register(form.username, form.email, form.password);
      await login(form.email, form.password);
      back();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  const fe = (f: string) => fieldError(error, f);

  return (
    <div className="container section">
      <form className="card auth-card" onSubmit={submit}>
        <h1>Реєстрація</h1>
        <p className="muted">Один акаунт — один голос у кожному опитуванні.</p>
        {!!error && !(error instanceof ApiError && error.status === 422) && <ErrorBox error={error} />}
        <label className="field">
          <span>Ім'я користувача</span>
          <input autoComplete="username" required minLength={3} maxLength={50} value={form.username} onChange={set('username')} />
          {fe('username') ? <small className="field-error">{fe('username')}</small> : <small>Латиниця, цифри, «_», «.», «-»</small>}
        </label>
        <label className="field">
          <span>Електронна пошта</span>
          <input type="email" autoComplete="email" required value={form.email} onChange={set('email')} />
          {fe('email') && <small className="field-error">{fe('email')}</small>}
        </label>
        <label className="field">
          <span>Пароль</span>
          <input type="password" autoComplete="new-password" required minLength={8} value={form.password} onChange={set('password')} />
          {fe('password') ? <small className="field-error">{fe('password')}</small> : <small>Щонайменше 8 символів</small>}
        </label>
        <button type="submit" className="btn btn-primary btn-block btn-lg" disabled={busy}>
          {busy ? 'Створюємо акаунт…' : 'Зареєструватися'}
        </button>
        <p className="auth-switch">
          Вже маєте акаунт? <Link to="/login">Увійти</Link>
        </p>
      </form>
    </div>
  );
}
