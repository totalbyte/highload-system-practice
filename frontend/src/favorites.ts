import { useSyncExternalStore } from 'react';

// Обране зберігається лише в цьому браузері (localStorage) — без змін схеми БД і API.
const KEY = 'polling:favorites';
const listeners = new Set<() => void>();
let cache: number[] | null = null;

function read(): number[] {
  if (cache) return cache;
  try {
    const parsed = JSON.parse(localStorage.getItem(KEY) ?? '[]');
    cache = Array.isArray(parsed) ? parsed.filter((x) => Number.isInteger(x)) : [];
  } catch {
    cache = [];
  }
  return cache;
}

function write(ids: number[]) {
  cache = ids;
  try {
    localStorage.setItem(KEY, JSON.stringify(ids));
  } catch {
    // приватний режим / заблоковане сховище — обране житиме до перезавантаження сторінки
  }
  listeners.forEach((l) => l());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  // Інша вкладка змінила обране — перечитати.
  const onStorage = (e: StorageEvent) => {
    if (e.key === KEY) {
      cache = null;
      listener();
    }
  };
  window.addEventListener('storage', onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener('storage', onStorage);
  };
}

export function useFavorites() {
  const ids = useSyncExternalStore(subscribe, read);
  return {
    ids,
    has: (id: number) => ids.includes(id),
    toggle: (id: number) => write(ids.includes(id) ? ids.filter((x) => x !== id) : [id, ...ids]),
    remove: (id: number) => write(ids.filter((x) => x !== id)),
  };
}
