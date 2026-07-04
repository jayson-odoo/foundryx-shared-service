/**
 * Generic in-memory query engine for MOCK services (Phase A only).
 *
 * It applies the same semantics the real backend will — recursive AND/OR
 * filtering, general search, sort, pagination — over an in-memory array, so the
 * frontend prototype behaves exactly like the server-side list. In Phase B the
 * real service replaces the mock and this file is no longer used at runtime.
 */
import type {
  FilterCondition,
  FilterGroup,
  FilterRule,
  ListQuery,
  ListResult,
} from '@/types/resource';

/** How the engine reads a filterable/sortable field off a row + which fields search hits. */
export interface QueryAdapter<T> {
  /** Resolve a (filter/sort) field name to a comparable value on the row. */
  getField: (row: T, field: string) => unknown;
  /** Fields the general search box matches (ILIKE-style contains). */
  searchFields: (keyof T | string)[];
}

function asString(v: unknown): string {
  if (v == null) return '';
  if (Array.isArray(v)) return v.join(' ');
  return String(v);
}

function evalCondition<T>(row: T, cond: FilterCondition, adapter: QueryAdapter<T>): boolean {
  const raw = adapter.getField(row, cond.field);
  const { operator, value } = cond;

  switch (operator) {
    case 'contains':
      return asString(raw).toLowerCase().includes(asString(value).toLowerCase());
    case 'eq':
      return asString(raw).toLowerCase() === asString(value).toLowerCase();
    case 'neq':
      return asString(raw).toLowerCase() !== asString(value).toLowerCase();
    case 'in': {
      const needles = (Array.isArray(value) ? value : [value]).map((v) => asString(v).toLowerCase());
      const hay = Array.isArray(raw) ? raw.map((v) => asString(v).toLowerCase()) : [asString(raw).toLowerCase()];
      return hay.some((h) => needles.includes(h));
    }
    case 'before':
      return new Date(asString(raw)).getTime() < new Date(asString(value)).getTime();
    case 'after':
      return new Date(asString(raw)).getTime() > new Date(asString(value)).getTime();
    case 'between': {
      if (!Array.isArray(value) || value.length < 2) return true;
      const t = new Date(asString(raw)).getTime();
      return (
        t >= new Date(asString(value[0])).getTime() && t <= new Date(asString(value[1])).getTime()
      );
    }
    case 'is_true':
      return raw === true;
    case 'is_false':
      return raw === false;
    default:
      return true;
  }
}

function evalRule<T>(row: T, rule: FilterRule, adapter: QueryAdapter<T>): boolean {
  if (rule.kind === 'condition') return evalCondition(row, rule, adapter);
  return evalGroup(row, rule, adapter);
}

function evalGroup<T>(row: T, group: FilterGroup, adapter: QueryAdapter<T>): boolean {
  if (!group.rules.length) return true;
  return group.combinator === 'and'
    ? group.rules.every((r) => evalRule(row, r, adapter))
    : group.rules.some((r) => evalRule(row, r, adapter));
}

/** Apply a full ListQuery to an array and return the matching page. */
export function runQuery<T>(rows: T[], query: ListQuery, adapter: QueryAdapter<T>): ListResult<T> {
  let result = rows;

  // Search (general, across declared fields).
  const search = query.search?.trim().toLowerCase();
  if (search) {
    result = result.filter((row) =>
      adapter.searchFields.some((f) =>
        asString(adapter.getField(row, String(f))).toLowerCase().includes(search),
      ),
    );
  }

  // Filter (recursive AND/OR).
  if (query.filter && query.filter.rules.length) {
    result = result.filter((row) => evalGroup(row, query.filter as FilterGroup, adapter));
  }

  // Sort.
  if (query.sort) {
    const { id, desc } = query.sort;
    result = [...result].sort((a, b) => {
      const av = asString(adapter.getField(a, id)).toLowerCase();
      const bv = asString(adapter.getField(b, id)).toLowerCase();
      if (av < bv) return desc ? 1 : -1;
      if (av > bv) return desc ? -1 : 1;
      return 0;
    });
  }

  const total = result.length;
  const start = query.page * query.pageSize;
  const data = result.slice(start, start + query.pageSize);
  return { data, total, page: query.page };
}

/** Simulate network latency so loading states are visible during the prototype. */
export function delay<T>(value: T, ms = 350): Promise<T> {
  return new Promise((resolve) => setTimeout(() => resolve(value), ms));
}
