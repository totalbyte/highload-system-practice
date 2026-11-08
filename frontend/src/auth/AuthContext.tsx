import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, tokenStore } from '../api/client';
import type { User } from '../api/types';

interface AuthState {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

/**
 * JWT лежить у localStorage браузера — сервер стану сесії не тримає (stateless, лаба 2),
 * тому будь-який backend за балансувальником приймає той самий токен.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [token, setToken] = useState(tokenStore.get);

  useEffect(() => {
    const sync = () => setToken(tokenStore.get());
    window.addEventListener('polling:auth', sync);
    window.addEventListener('storage', sync);
    return () => {
      window.removeEventListener('polling:auth', sync);
      window.removeEventListener('storage', sync);
    };
  }, []);

  // Після входу / виходу змінюються видимі чернетки й «мій голос» — скидаємо закешоване і перезапитуємо
  // відкрите. Лише при справжній зміні токена: скидання на першому рендері лишало б сторінку в «Завантаження…».
  const previous = useRef(token);
  useEffect(() => {
    if (previous.current === token) return;
    previous.current = token;
    queryClient.resetQueries({ predicate: (q) => q.queryKey[0] !== 'me' });
  }, [token, queryClient]);

  const me = useQuery({ queryKey: ['me', token], queryFn: api.me, enabled: !!token, staleTime: Infinity, retry: false });

  const value: AuthState = {
    user: token ? (me.data ?? null) : null,
    loading: !!token && me.isPending,
    login: async (email, password) => tokenStore.set(await api.login(email, password)),
    logout: () => tokenStore.set(null),
  };
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}
