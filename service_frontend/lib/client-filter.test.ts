import { describe, expect, it } from 'vitest';
import type { FilterGroup } from '@/types/resource';
import { matchesFilterGroup } from './client-filter';

/** ONE client-side matcher for small lists filtered in the browser (crew pass
 * 70e96f2b: the Followers list had no filter at all). */
interface Row {
  name: string;
  addedBy: string;
  since: string;
}
const row: Row = { name: 'Manager B', addedBy: 'staff', since: '2026-11-17T04:00:00Z' };
const val = (r: Row, f: string) => (r as unknown as Record<string, string>)[f] ?? null;
const g = (rules: FilterGroup['rules'], combinator: 'and' | 'or' = 'and'): FilterGroup => ({ kind: 'group', combinator, rules });

describe('matchesFilterGroup', () => {
  it('empty / missing group matches', () => {
    expect(matchesFilterGroup(row, null, val)).toBe(true);
    expect(matchesFilterGroup(row, g([]), val)).toBe(true);
  });
  it('in (multi-select) matches either value', () => {
    expect(matchesFilterGroup(row, g([{ kind: 'condition', field: 'addedBy', operator: 'in', value: ['staff', 'self'] }]), val)).toBe(true);
    expect(matchesFilterGroup(row, g([{ kind: 'condition', field: 'addedBy', operator: 'in', value: ['self'] }]), val)).toBe(false);
  });
  it('contains / eq / neq are case-insensitive', () => {
    expect(matchesFilterGroup(row, g([{ kind: 'condition', field: 'name', operator: 'contains', value: 'manager' }]), val)).toBe(true);
    expect(matchesFilterGroup(row, g([{ kind: 'condition', field: 'name', operator: 'eq', value: 'MANAGER B' }]), val)).toBe(true);
    expect(matchesFilterGroup(row, g([{ kind: 'condition', field: 'name', operator: 'neq', value: 'manager b' }]), val)).toBe(false);
  });
  it('date before / after / between compare by day', () => {
    expect(matchesFilterGroup(row, g([{ kind: 'condition', field: 'since', operator: 'after', value: '2026-11-16' }]), val)).toBe(true);
    expect(matchesFilterGroup(row, g([{ kind: 'condition', field: 'since', operator: 'before', value: '2026-11-17' }]), val)).toBe(false);
    expect(matchesFilterGroup(row, g([{ kind: 'condition', field: 'since', operator: 'between', value: ['2026-11-17', '2026-11-17'] }]), val)).toBe(true);
  });
  it('and / or groups combine, nested groups recurse', () => {
    const a = { kind: 'condition' as const, field: 'name', operator: 'contains' as const, value: 'zzz' };
    const b = { kind: 'condition' as const, field: 'addedBy', operator: 'eq' as const, value: 'staff' };
    expect(matchesFilterGroup(row, g([a, b], 'or'), val)).toBe(true);
    expect(matchesFilterGroup(row, g([a, b], 'and'), val)).toBe(false);
    expect(matchesFilterGroup(row, g([g([a, b], 'or'), b]), val)).toBe(true);
  });
});
