/**
 * Structured cron helpers (plan sprint-2/09 D9) - the schedule trigger's
 * builder compiles a frequency + sub-fields to a standard 5-field cron string,
 * and parses one back for editing. A raw-cron escape hatch bypasses this; an
 * unrecognised string drops the builder into raw mode (see `parseCron`).
 *
 * Pure + framework-free so it is unit-tested directly. `croniter` (backend)
 * owns the actual next-run computation - this is display/compile only.
 */

export type CronFrequency = 'minute' | 'hour' | 'day' | 'week' | 'month';

export interface CronState {
  frequency: CronFrequency;
  /** minute freq - every N minutes (1 = every minute). */
  interval: number;
  /** minute-of-hour (hour/day/week/month freqs). */
  minute: number;
  /** hour-of-day (day/week/month freqs). */
  hour: number;
  /** 0=Sun … 6=Sat (week freq). */
  dayOfWeek: number;
  /** 1-31 (month freq). */
  dayOfMonth: number;
}

export const DEFAULT_CRON_STATE: CronState = {
  frequency: 'day',
  interval: 1,
  minute: 0,
  hour: 9,
  dayOfWeek: 1,
  dayOfMonth: 1,
};

export const WEEKDAYS: { value: number; label: string }[] = [
  { value: 0, label: 'Sunday' },
  { value: 1, label: 'Monday' },
  { value: 2, label: 'Tuesday' },
  { value: 3, label: 'Wednesday' },
  { value: 4, label: 'Thursday' },
  { value: 5, label: 'Friday' },
  { value: 6, label: 'Saturday' },
];

function clamp(n: number, lo: number, hi: number): number {
  if (Number.isNaN(n)) return lo;
  return Math.min(hi, Math.max(lo, Math.trunc(n)));
}

/** Compile a builder state to a 5-field cron string (min hour dom mon dow). */
export function compileCron(state: CronState): string {
  const minute = clamp(state.minute, 0, 59);
  const hour = clamp(state.hour, 0, 23);
  const dow = clamp(state.dayOfWeek, 0, 6);
  const dom = clamp(state.dayOfMonth, 1, 31);
  const interval = clamp(state.interval, 1, 59);
  switch (state.frequency) {
    case 'minute':
      return `${interval === 1 ? '*' : `*/${interval}`} * * * *`;
    case 'hour':
      return `${minute} * * * *`;
    case 'day':
      return `${minute} ${hour} * * *`;
    case 'week':
      return `${minute} ${hour} * * ${dow}`;
    case 'month':
      return `${minute} ${hour} ${dom} * *`;
  }
}

/**
 * Best-effort parse of a 5-field cron back into a builder state. Returns null
 * when the string isn't one the structured builder can represent (→ raw mode).
 */
export function parseCron(cron: string): CronState | null {
  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) return null;
  const [min, hr, dom, mon, dow] = parts;
  if (mon !== '*') return null;
  const num = (s: string): number | null => (/^\d+$/.test(s) ? Number(s) : null);

  // minute / hour freqs both have hr=dom=dow=*; distinguish on the minute field.
  if (hr === '*' && dom === '*' && dow === '*') {
    if (min === '*') return { ...DEFAULT_CRON_STATE, frequency: 'minute', interval: 1 };
    const m = /^\*\/(\d+)$/.exec(min);
    if (m) return { ...DEFAULT_CRON_STATE, frequency: 'minute', interval: Number(m[1]) };
    const minute = num(min);
    if (minute === null) return null;
    return { ...DEFAULT_CRON_STATE, frequency: 'hour', minute };
  }
  const minute = num(min);
  if (minute === null) return null;
  const hour = num(hr);
  if (hour === null) return null;

  // week freq: M H * * D
  if (dom === '*' && dow !== '*') {
    const d = num(dow);
    if (d === null || d > 6) return null;
    return { ...DEFAULT_CRON_STATE, frequency: 'week', minute, hour, dayOfWeek: d };
  }
  // month freq: M H D * *
  if (dow === '*' && dom !== '*') {
    const d = num(dom);
    if (d === null || d < 1 || d > 31) return null;
    return { ...DEFAULT_CRON_STATE, frequency: 'month', minute, hour, dayOfMonth: d };
  }
  // day freq: M H * * *
  if (dom === '*' && dow === '*') {
    return { ...DEFAULT_CRON_STATE, frequency: 'day', minute, hour };
  }
  return null;
}

function hhmm(hour: number, minute: number): string {
  return `${String(clamp(hour, 0, 23)).padStart(2, '0')}:${String(clamp(minute, 0, 59)).padStart(2, '0')}`;
}

/** Human-readable summary for a 5-field cron (builder preview + node card). */
export function describeCron(cron: string): string {
  const state = parseCron(cron);
  if (!state) return `Custom schedule (${cron})`;
  switch (state.frequency) {
    case 'minute':
      return state.interval === 1 ? 'Every minute' : `Every ${state.interval} minutes`;
    case 'hour':
      return `Hourly at :${String(clamp(state.minute, 0, 59)).padStart(2, '0')}`;
    case 'day':
      return `Daily at ${hhmm(state.hour, state.minute)}`;
    case 'week':
      return `Weekly on ${WEEKDAYS[state.dayOfWeek]?.label ?? '?'} at ${hhmm(state.hour, state.minute)}`;
    case 'month':
      return `Monthly on day ${state.dayOfMonth} at ${hhmm(state.hour, state.minute)}`;
  }
}
