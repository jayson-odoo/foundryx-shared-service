/**
 * Pure helpers behind the Foundryx UIUX fields (playbook 0.71.0 "Fields";
 * playbook-uiux.md). No React, no zone maths beyond calendar-day keys, so
 * every rule here is tested on its own (`fields.test.ts`).
 */

const MONTHS = [
  'jan', 'feb', 'mar', 'apr', 'may', 'jun',
  'jul', 'aug', 'sep', 'oct', 'nov', 'dec',
];

function monthIndex(word: string): number | null {
  const i = MONTHS.indexOf(word.slice(0, 3).toLowerCase());
  return i < 0 ? null : i + 1;
}

function key(y: number, m: number, d: number): string | null {
  if (m < 1 || m > 12 || d < 1) return null;
  const last = new Date(Date.UTC(y, m, 0)).getUTCDate();
  if (d > last) return null;
  return `${String(y).padStart(4, '0')}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
}

function addDays(dayKey: string, days: number): string {
  const [y, m, d] = dayKey.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10);
}

function fullYear(text: string): number {
  const n = Number(text);
  return text.length <= 2 ? 2000 + n : n;
}

/**
 * A typed date, read into a calendar-day key ("2026-11-14"), or null when it
 * cannot be read. `today` is the calendar day the words count from (a key in
 * the viewer's zone). Takes "today", "tomorrow", "yesterday", "14/11/2026",
 * "14-11-26", "14.11.2026", "14 Nov", "14 November 2026", "Nov 14 2026" and
 * "2026-11-14". A day with no year is in today's year.
 */
export function parseTypedDate(text: string, today: string): string | null {
  const t = text.trim().toLowerCase().replace(/,/g, ' ').replace(/\s+/g, ' ');
  if (!t) return null;
  if (t === 'today') return today;
  if (t === 'tomorrow') return addDays(today, 1);
  if (t === 'yesterday') return addDays(today, -1);
  const thisYear = Number(today.slice(0, 4));

  let m = t.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/);
  if (m) return key(Number(m[1]), Number(m[2]), Number(m[3]));

  m = t.match(/^(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2}|\d{4}))?$/);
  if (m) return key(m[3] ? fullYear(m[3]) : thisYear, Number(m[2]), Number(m[1]));

  m = t.match(/^(\d{1,2}) ([a-z]+)(?: (\d{2}|\d{4}))?$/);
  if (m) {
    const month = monthIndex(m[2]);
    return month ? key(m[3] ? fullYear(m[3]) : thisYear, month, Number(m[1])) : null;
  }

  m = t.match(/^([a-z]+) (\d{1,2})(?: (\d{2}|\d{4}))?$/);
  if (m) {
    const month = monthIndex(m[1]);
    return month ? key(m[3] ? fullYear(m[3]) : thisYear, month, Number(m[2])) : null;
  }
  return null;
}

/** "ending a91c": how a saved secret is named afterwards (never the value). */
export function secretEnding(value: string | null | undefined, length = 4): string {
  const v = (value ?? '').trim();
  return v ? `ending ${v.slice(-length)}` : '';
}

export type PasswordStrengthLevel = 0 | 1 | 2 | 3;

export interface PasswordStrength {
  /** 0 Weak, 1 Fair, 2 Good, 3 Strong. */
  level: PasswordStrengthLevel;
  label: 'Weak' | 'Fair' | 'Good' | 'Strong';
  /** The one thing still missing, or null when Strong. */
  missing: string | null;
}

const LABELS: PasswordStrength['label'][] = ['Weak', 'Fair', 'Good', 'Strong'];

/**
 * Four bars under a new password (playbook "Password strength"): it grows
 * with the mix (a number, upper and lower case, a symbol), plus one step for
 * 12 or more characters. Under 8 characters it stays Weak. `missing` names
 * the first gap: length, then a number, a capital, a symbol.
 */
export function passwordStrength(password: string): PasswordStrength {
  const checks: [boolean, string][] = [
    [password.length >= 8, 'Use 8 or more characters'],
    [/\d/.test(password), 'Add a number'],
    [/[A-Z]/.test(password) && /[a-z]/.test(password), 'Add a capital letter'],
    [/[^A-Za-z0-9]/.test(password), 'Add a symbol'],
  ];
  const missing = checks.find(([ok]) => !ok)?.[1] ?? null;
  if (!checks[0][0]) return { level: 0, label: 'Weak', missing };
  const mix = checks.slice(1).filter(([ok]) => ok).length;
  const level = Math.min(3, mix + (password.length >= 12 ? 1 : 0)) as PasswordStrengthLevel;
  return { level, label: LABELS[level], missing };
}

/** A typed value kept inside [min, max], as typed otherwise (FX-12). */
export function clampValue(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

/** Where the step grid starts: min, or 0 when there is no min. */
function gridOrigin(min: number): number {
  return Number.isFinite(min) ? min : 0;
}

/** The value a step lands on: clamped to [min, max] and on the step grid from min. */
export function snapToStep(value: number, min: number, max: number, step: number): number {
  if (!(step > 0)) return clampValue(value, min, max);
  const origin = gridOrigin(min);
  const steps = Math.round((value - origin) / step);
  const snapped = origin + steps * step;
  const decimals = (String(step).split('.')[1] ?? '').length;
  return clampValue(Number(snapped.toFixed(decimals)), min, max);
}

/**
 * A stepper's next value: one step up or down, clamped. A value between two
 * steps (typed, FX-12) moves to the next step in that direction, the way a
 * browser number field does: 6.5 goes up to 7 and down to 6.
 */
export function stepValue(value: number, direction: 1 | -1, min: number, max: number, step: number): number {
  if (!(step > 0)) return clampValue(value, min, max);
  const position = (value - gridOrigin(min)) / step;
  if (Math.abs(position - Math.round(position)) < 1e-9) {
    return snapToStep(value + direction * step, min, max, step);
  }
  const next = direction > 0 ? Math.ceil(position) : Math.floor(position);
  return snapToStep(gridOrigin(min) + next * step, min, max, step);
}
