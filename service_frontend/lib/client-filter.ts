/**
 * ONE client-side matcher for a ResourceList whose whole row set is small and
 * already in the browser (the fetcher pages it locally): evaluates the shell's
 * filter tree (`FilterGroup`) against each row. Server lists translate the same
 * tree server-side (`filter_translator.py`); this is the in-browser twin.
 *
 * `valueOf(row, field)` returns the row's value for a declared filter field:
 * a string (text / enum / ISO date), a boolean, or null.
 */
import type { FilterGroup, FilterRule } from '@/types/resource';

export type ClientFilterValue = string | boolean | null;

const day = (v: unknown): string => String(v ?? '').slice(0, 10);

function matchesRule<T>(row: T, rule: FilterRule, valueOf: (row: T, field: string) => ClientFilterValue): boolean {
  if (rule.kind === 'group') return matchesFilterGroup(row, rule, valueOf);
  const raw = valueOf(row, rule.field);
  if (rule.operator === 'is_true') return raw === true;
  if (rule.operator === 'is_false') return raw === false;
  const value = String(raw ?? '').toLowerCase();
  const target = rule.value;
  switch (rule.operator) {
    case 'contains':
      return value.includes(String(target ?? '').toLowerCase());
    case 'eq':
      return value === String(target ?? '').toLowerCase();
    case 'neq':
      return value !== String(target ?? '').toLowerCase();
    case 'in':
      return (Array.isArray(target) ? target : [target]).some((t) => value === String(t ?? '').toLowerCase());
    case 'before':
      return Boolean(raw) && day(raw) < day(target);
    case 'after':
      return Boolean(raw) && day(raw) > day(target);
    case 'between': {
      const [from, to] = Array.isArray(target) ? target : [];
      return Boolean(raw) && (!from || day(raw) >= day(from)) && (!to || day(raw) <= day(to));
    }
    default:
      return true;
  }
}

export function matchesFilterGroup<T>(
  row: T,
  group: FilterGroup | null | undefined,
  valueOf: (row: T, field: string) => ClientFilterValue,
): boolean {
  if (!group || group.rules.length === 0) return true;
  const results = group.rules.map((rule) => matchesRule(row, rule, valueOf));
  return group.combinator === 'or' ? results.some(Boolean) : results.every(Boolean);
}
