import type { PollStatus } from './api/types';

const dateFmt = new Intl.DateTimeFormat('uk-UA', { day: '2-digit', month: '2-digit', year: 'numeric' });
const dateTimeFmt = new Intl.DateTimeFormat('uk-UA', {
  day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
});
const timeFmt = new Intl.DateTimeFormat('uk-UA', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

export const formatDate = (iso: string) => dateFmt.format(new Date(iso));
export const formatDateTime = (iso: string) => dateTimeFmt.format(new Date(iso));
export const formatTime = (iso: string) => timeFmt.format(new Date(iso));

/** Номер у стилі реєстру: № 0042-оп. */
export const pollNumber = (id: number) => `№ ${String(id).padStart(4, '0')}-оп`;

export function plural(n: number, one: string, few: string, many: string) {
  const m10 = n % 10;
  const m100 = n % 100;
  if (m10 === 1 && m100 !== 11) return one;
  if (m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14)) return few;
  return many;
}

export const votesLabel = (n: number) => `${n.toLocaleString('uk-UA')} ${plural(n, 'голос', 'голоси', 'голосів')}`;

export type Phase = 'draft' | 'scheduled' | 'open' | 'expired' | 'closed';

/** Статус active ще не означає «можна голосувати»: фонового закривача немає, дати перевіряються окремо. */
export function phaseOf(p: { status: PollStatus; startsAt: string | null; endsAt: string }, now = Date.now()): Phase {
  if (p.status === 'draft') return 'draft';
  if (p.status === 'closed') return 'closed';
  if (p.startsAt && now < Date.parse(p.startsAt)) return 'scheduled';
  if (now >= Date.parse(p.endsAt)) return 'expired';
  return 'open';
}

export const phaseLabel: Record<Phase, string> = {
  draft: 'Чернетка',
  scheduled: 'Ще не розпочато',
  open: 'Триває голосування',
  expired: 'Час голосування вийшов',
  closed: 'Завершено',
};

export function timeLeft(endsAt: string, now = Date.now()) {
  const ms = Date.parse(endsAt) - now;
  if (ms <= 0) return null;
  const days = Math.floor(ms / 86_400_000);
  if (days >= 1) return `${days} ${plural(days, 'день', 'дні', 'днів')}`;
  const hours = Math.floor(ms / 3_600_000);
  if (hours >= 1) return `${hours} ${plural(hours, 'година', 'години', 'годин')}`;
  return `${Math.max(1, Math.floor(ms / 60_000))} хв`;
}
