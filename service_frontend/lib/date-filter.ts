/**
 * Day filters on moments, sent as the user's own local days.
 *
 * The date filters (the Filters panel's range and before/after, the
 * Foundryx UIUX header range) hold calendar days, `YYYY-MM-DD`, picked in the
 * user's zone ("Today" in Kuala Lumpur starts at 16:00 UTC the day before).
 * The list API compares a moment column against what it is sent
 * (`filter_translator.py`: `between` is `>= from AND <= to`, `before` is `<`,
 * `after` is `>`), and a bare day reads there as UTC midnight. Sent as days,
 * "Today" became "from UTC midnight to the same UTC midnight" and matched
 * nothing, and every other range was shifted by the zone offset and lost
 * its last day.
 *
 * So, just before a list asks the server, each condition on a moment field
 * (`type: 'date'`, not `calendarDate`) becomes exact instants:
 * - `between [from, to]` -> from the start of `from` to the last millisecond
 *   of `to` (whole days, both ends included);
 * - `before day` -> before the start of that day;
 * - `after day` -> after the start of that day (as today: the day itself counts).
 * The list's own state (address, saved segments, the pickers) keeps the days.
 */
import { zonedTimeToUtc } from '@/lib/datetime';
import type { FilterFieldDef, FilterGroup, FilterRule, FilterValue } from '@/types/resource';

const DAY_KEY = /^\d{4}-\d{2}-\d{2}$/;

function nextDayKey(day: string): string {
  const [y, m, d] = day.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d + 1)).toISOString().slice(0, 10);
}

/** The first moment of `day` in `timeZone`, as an ISO UTC instant. */
export function startOfLocalDay(day: string, timeZone: string): string {
  return (zonedTimeToUtc(`${day}T00:00`, timeZone) as Date).toISOString();
}

/** The last millisecond of `day` in `timeZone`, as an ISO UTC instant. */
export function endOfLocalDay(day: string, timeZone: string): string {
  const next = zonedTimeToUtc(`${nextDayKey(day)}T00:00`, timeZone) as Date;
  return new Date(next.getTime() - 1).toISOString();
}

/** The `date` fields whose values are moments, by field name. */
export function momentDateFields(fields: FilterFieldDef[] | undefined): string[] {
  return (fields ?? []).filter((f) => f.type === 'date' && !f.calendarDate).map((f) => f.field);
}

function convertValue(operator: string, value: FilterValue, timeZone: string): FilterValue {
  const isDay = (v: unknown): v is string => typeof v === 'string' && DAY_KEY.test(v);
  if (operator === 'between' && Array.isArray(value)) {
    const [from, to, ...rest] = value;
    return [
      isDay(from) ? startOfLocalDay(from, timeZone) : from,
      isDay(to) ? endOfLocalDay(to, timeZone) : to,
      ...rest,
    ];
  }
  if ((operator === 'before' || operator === 'after') && isDay(value)) {
    return startOfLocalDay(value, timeZone);
  }
  return value;
}

function convertRule(rule: FilterRule, fields: Set<string>, timeZone: string): FilterRule {
  if (rule.kind === 'group') return convertGroup(rule, fields, timeZone);
  if (!fields.has(rule.field)) return rule;
  const value = convertValue(rule.operator, rule.value, timeZone);
  return value === rule.value ? rule : { ...rule, value };
}

function convertGroup(group: FilterGroup, fields: Set<string>, timeZone: string): FilterGroup {
  return { ...group, rules: group.rules.map((r) => convertRule(r, fields, timeZone)) };
}

/**
 * The filter as the server should get it: day conditions on the named moment
 * fields as instants in `timeZone`; everything else untouched.
 */
export function toServerDateFilter(
  filter: FilterGroup | null | undefined,
  momentFields: string[],
  timeZone: string,
): FilterGroup | null | undefined {
  if (!filter || momentFields.length === 0) return filter;
  return convertGroup(filter, new Set(momentFields), timeZone);
}
