import type {
  CreatePollRequest, Paged, PollDetails, PollResults, PollStatus, PollSummary, ServedBy, Token, User, Vote,
} from './types';

/** RFC 7807 ProblemDetails від API, перетворений на виняток. */
export class ApiError extends Error {
  status: number;
  errors: Record<string, string[]>;

  constructor(status: number, message: string, errors: Record<string, string[]> = {}) {
    super(message);
    this.status = status;
    this.errors = errors;
  }
}

const TOKEN_KEY = 'polling:token';

export const tokenStore = {
  get(): string | null {
    try {
      const raw = localStorage.getItem(TOKEN_KEY);
      if (!raw) return null;
      const token = JSON.parse(raw) as Token;
      return new Date(token.expiresAt) > new Date() ? token.accessToken : null;
    } catch {
      return null;
    }
  },
  set(token: Token | null) {
    try {
      if (token) localStorage.setItem(TOKEN_KEY, JSON.stringify(token));
      else localStorage.removeItem(TOKEN_KEY);
    } catch {
      // сховище недоступне — користувач просто лишиться неавторизованим
    }
    window.dispatchEvent(new Event('polling:auth'));
  },
};

async function request<T>(method: string, path: string, body?: unknown): Promise<{ data: T; servedBy: ServedBy }> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  const token = tokenStore.get();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers['Content-Type'] = 'application/json';

  let res: Response;
  try {
    res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new ApiError(0, 'Сервер недоступний. Перевірте, що стек запущено (docker compose up).');
  }

  const servedBy = { instance: res.headers.get('X-Instance-ID'), cache: res.headers.get('X-Cache') };
  const text = await res.text();
  let json: any = null;
  if (text && res.headers.get('Content-Type')?.includes('json')) {
    try {
      json = JSON.parse(text);
    } catch {
      json = null;
    }
  }

  if (!res.ok) {
    // Прострочений або недійсний токен — забуваємо його, щоб інтерфейс показав «Увійти».
    if (res.status === 401 && token) tokenStore.set(null);
    const fallback = res.status === 503 ? 'Сервіс тимчасово недоступний, спробуйте пізніше.' : `Помилка HTTP ${res.status}`;
    throw new ApiError(res.status, json?.detail ?? json?.title ?? fallback, json?.errors ?? {});
  }
  return { data: json as T, servedBy };
}

const data = async <T>(p: Promise<{ data: T }>) => (await p).data;

export interface ListParams {
  status?: PollStatus;
  creatorId?: number;
  page?: number;
  pageSize?: number;
}

export type ResultsWithSource = PollResults & { servedBy: ServedBy };

export const api = {
  login: (email: string, password: string) => data(request<Token>('POST', '/api/auth/login', { email, password })),
  register: (username: string, email: string, password: string) =>
    data(request<User>('POST', '/api/auth/register', { username, email, password })),
  me: () => data(request<User>('GET', '/api/auth/me')),

  listPolls: (params: ListParams) => {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined) query.set(k, String(v));
    });
    return data(request<Paged<PollSummary>>('GET', `/api/polls?${query}`));
  },
  getPoll: (id: number) => data(request<PollDetails>('GET', `/api/polls/${id}`)),
  createPoll: (body: CreatePollRequest) => data(request<PollDetails>('POST', '/api/polls', body)),
  publishPoll: (id: number) => data(request<PollDetails>('PATCH', `/api/polls/${id}/publish`)),
  closePoll: (id: number) => data(request<PollDetails>('PATCH', `/api/polls/${id}/close`)),
  deletePoll: (id: number) => data(request<null>('DELETE', `/api/polls/${id}`)),

  /** Результати разом із заголовками — інтерфейс показує, який вузол відповів і чи був це HIT кешу. */
  getResults: async (id: number): Promise<ResultsWithSource> => {
    const { data: results, servedBy } = await request<PollResults>('GET', `/api/polls/${id}/results`);
    return { ...results, servedBy };
  },
  /** null — користувач ще не голосував (API відповідає 404). */
  getMyVote: async (id: number) => {
    try {
      return await data(request<Vote>('GET', `/api/polls/${id}/vote`));
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) return null;
      throw e;
    }
  },
  vote: (id: number, optionId: number) => data(request<Vote>('POST', `/api/polls/${id}/vote`, { optionId })),
};
