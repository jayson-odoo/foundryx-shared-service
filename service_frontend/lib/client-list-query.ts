/**
 * Apply a Resource-shell `ListQuery` (search · enum filters · sort · page) to a
 * small list already held client-side. For lists whose backend returns the
 * whole set in one call (a company's keys, receivers, form maps): the fetcher
 * loads it once, then this does what a server list would.
 */
import type { FilterGroup, FilterRule, ListQuery, ListResult } from '@/types/resource';

export interface ClientListSpec<T> {
  /** Texts the general search matches (case-insensitive contains). */
  searchText: (row: T) => string[];
  /** Comparable value per sortable column id (and per filter field). */
  value: (row: T, field: string) => string | number | null;
}

function matchRule<T>(row: T, rule: FilterRule, spec: ClientListSpec<T>): boolean {
  if (rule.kind === 'group') return matchGroup(row, rule, spec);
  const actual = spec.value(row, rule.field);
  const text = actual === null ? '' : String(actual).toLowerCase();
  const wanted = rule.value;
  switch (rule.operator) {
    case 'in':
      return Array.isArray(wanted) && wanted.map((v) => v.toLowerCase()).includes(text);
    case 'eq':
      return text === String(wanted ?? '').toLowerCase();
    case 'neq':
      return text !== String(wanted ?? '').toLowerCase();
    case 'contains':
      return text.includes(String(wanted ?? '').toLowerCase());
    default:
      return true;
  }
}

function matchGroup<T>(row: T, group: FilterGroup, spec: ClientListSpec<T>): boolean {
  if (group.rules.length === 0) return true;
  const results = group.rules.map((r) => matchRule(row, r, spec));
  return group.combinator === 'or' ? results.some(Boolean) : results.every(Boolean);
}

export function applyClientQuery<T>(
  rows: T[],
  query: ListQuery,
  spec: ClientListSpec<T>,
): ListResult<T> {
  let out = rows;
  const search = query.search?.trim().toLowerCase();
  if (search) {
    out = out.filter((r) => spec.searchText(r).some((t) => t.toLowerCase().includes(search)));
  }
  if (query.filter) {
    const filter = query.filter;
    out = out.filter((r) => matchGroup(r, filter, spec));
  }
  const sort = query.sort;
  if (sort) {
    const dir = sort.desc ? -1 : 1;
    out = [...out].sort((a, b) => {
      const va = spec.value(a, sort.id);
      const vb = spec.value(b, sort.id);
      // Blanks sort last whatever the direction.
      if (va === null || va === '') return vb === null || vb === '' ? 0 : 1;
      if (vb === null || vb === '') return -1;
      if (typeof va === 'number' && typeof vb === 'number') return (va - vb) * dir;
      return String(va).localeCompare(String(vb), undefined, { numeric: true }) * dir;
    });
  }
  const start = query.page * query.pageSize;
  return { data: out.slice(start, start + query.pageSize), total: out.length, page: query.page };
}
