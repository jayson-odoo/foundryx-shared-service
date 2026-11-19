/**
 * Pure rules behind the Foundryx UIUX list (playbook 0.71.0 "Lists"), kept
 * apart from the components so each one is tested on its own:
 * - Smart view: which columns stay in the table, which move into info lines,
 *   and how wide each one is;
 * - which kind of header search or filter a column gets;
 * - the header filters as list filter conditions, and back again;
 * - the pager's page numbers and its "Showing" line.
 */
import type { FxColumnKind } from '@/components/platform/resource-list/types';
import type {
  FilterCondition,
  FilterFieldDef,
  FilterGroup,
  FilterRule,
} from '@/types/resource';

// ---------------------------------------------------------------- Smart view

/** Cap for long text such as Title or Description (wraps to 2 lines). */
export const FX_LONG_CAP = 320;
/** Cap for every other column. */
export const FX_COLUMN_CAP = 200;
/** At least this many data columns stay in the table. */
export const FX_MIN_TABLE_COLUMNS = 2;

export interface FxColumnNeed {
  id: string;
  /** Width the header and values need, before the cap. */
  need: number;
  /** Long text: capped at FX_LONG_CAP instead of FX_COLUMN_CAP. */
  long?: boolean;
  /** Tick box or row actions: never moves, never counts as a data column. */
  fixed?: boolean;
}

export interface FxSmartPlan {
  /** Columns that stay in the table, in order. */
  inTable: string[];
  /** Columns shown as info lines under each row, in order. */
  infoLines: string[];
  /** Width per in-table column, spare width spread evenly. */
  widths: Record<string, number>;
  /** True when even two columns don't fit (the list should become cards). */
  tooNarrow: boolean;
}

/** A column's width at rest: what it needs, up to its cap. */
export function cappedNeed(col: FxColumnNeed): number {
  const cap = col.long ? FX_LONG_CAP : FX_COLUMN_CAP;
  return Math.max(0, Math.min(Math.ceil(col.need), col.fixed ? col.need : cap));
}

/**
 * Smart view (playbook "Lists"): every column as wide as it needs up to its
 * cap; when they don't fit, the right-most data columns move one at a time
 * into info lines, keeping at least two in the table; spare width spreads
 * evenly. An unknown width (0, nothing measured yet) keeps every column.
 */
export function planSmartColumns(
  cols: FxColumnNeed[],
  available: number,
): FxSmartPlan {
  const widthOf = new Map(cols.map((c) => [c.id, cappedNeed(c)]));
  const inTable = cols.map((c) => c.id);
  const infoLines: string[] = [];
  const total = () => inTable.reduce((sum, id) => sum + (widthOf.get(id) ?? 0), 0);
  const dataCount = () =>
    inTable.filter((id) => !cols.find((c) => c.id === id)?.fixed).length;

  let tooNarrow = false;
  if (available > 0) {
    while (total() > available) {
      if (dataCount() <= FX_MIN_TABLE_COLUMNS) {
        tooNarrow = true;
        break;
      }
      // The right-most data column moves first.
      let index = -1;
      for (let i = inTable.length - 1; i >= 0; i--) {
        if (!cols.find((c) => c.id === inTable[i])?.fixed) {
          index = i;
          break;
        }
      }
      if (index < 0) break;
      const [moved] = inTable.splice(index, 1);
      infoLines.unshift(moved);
    }
  }

  const widths: Record<string, number> = {};
  const spare = available > 0 ? Math.max(0, available - total()) : 0;
  const growable = inTable.filter((id) => !cols.find((c) => c.id === id)?.fixed);
  const share = growable.length ? Math.floor(spare / growable.length) : 0;
  for (const id of inTable) {
    const base = widthOf.get(id) ?? 0;
    widths[id] = growable.includes(id) ? base + share : base;
  }
  return { inTable, infoLines, widths, tooNarrow };
}

// ------------------------------------------------------------ column kinds

/** Values that read as a date: ISO dates and date-times. */
const ISO_DATE = /^\d{4}-\d{2}-\d{2}([T ][\d:.]+(Z|[+-]\d{2}:?\d{2})?)?$/;

/**
 * The header search or filter a column gets (playbook: "filters by that
 * column's type, read from its values"), or null for none.
 *
 * The list's own filter fields come first, because the server only filters
 * what the list declares: a column with no matching filter field gets no
 * header search or filter. Then the page's `fx.columnKind`, then the field's
 * type, then the values on screen.
 *
 * - `text` -> search over the header (contains)
 * - `date` -> From and To range (between, whole days)
 * - `status` -> ticks, one per declared option (in)
 * - `number` and `amount` -> none for now: the list API only ranges dates.
 */
export function fxHeaderFilterKind(
  field: FilterFieldDef | undefined,
  declared: FxColumnKind | undefined,
  sample: unknown[] = [],
): Exclude<FxColumnKind, 'number' | 'amount'> | null {
  if (!field) return null;
  const ops = field.operators;
  const allows = (op: FilterCondition['operator']) => !ops || ops.length === 0 || ops.includes(op);

  const fromField = (): FxColumnKind | null => {
    if (field.type === 'date') return 'date';
    if (field.type === 'enum') return 'status';
    if (field.type === 'text') {
      const values = sample.filter((v) => v !== null && v !== undefined && v !== '');
      if (values.length > 0 && values.every((v) => typeof v === 'string' && ISO_DATE.test(v))) {
        return 'date';
      }
      if (values.length > 0 && values.every((v) => typeof v === 'number')) return 'number';
      return 'text';
    }
    return null;
  };

  const kind = declared ?? fromField();
  if (kind === 'text' && field.type === 'text' && allows('contains')) return 'text';
  if (kind === 'date' && field.type === 'date' && allows('between')) return 'date';
  if (kind === 'status' && field.type === 'enum' && allows('in') && (field.options?.length ?? 0) > 0) {
    return 'status';
  }
  return null;
}

// ---------------------------------------------------------- header filters

/** One column's header filter value. */
export type FxHeaderValue =
  | { kind: 'text'; text: string }
  | { kind: 'date'; from: string; to: string }
  | { kind: 'status'; values: string[] };

export type FxHeaderFilters = Record<string, FxHeaderValue>;

/** True when the value filters nothing (empty search, no range, no ticks). */
export function isEmptyHeaderValue(v: FxHeaderValue | undefined): boolean {
  if (!v) return true;
  if (v.kind === 'text') return v.text.trim() === '';
  // The list API needs both ends of a range.
  if (v.kind === 'date') return !v.from || !v.to;
  return v.values.length === 0;
}

function toCondition(field: string, v: FxHeaderValue): FilterCondition {
  if (v.kind === 'text') {
    return { kind: 'condition', field, operator: 'contains', value: v.text.trim() };
  }
  if (v.kind === 'date') {
    return { kind: 'condition', field, operator: 'between', value: [v.from, v.to] };
  }
  return { kind: 'condition', field, operator: 'in', value: v.values };
}

/**
 * The list filter sent to the server: the Filters panel's own tree, plus the
 * header filters as one AND group. With no header filter the panel's tree goes
 * through untouched, exactly as with the switch off.
 */
export function combineFilters(
  panel: FilterGroup | null,
  header: FxHeaderFilters,
): FilterGroup | null {
  const conditions = Object.entries(header)
    .filter(([, v]) => !isEmptyHeaderValue(v))
    .map(([field, v]) => toCondition(field, v));
  if (conditions.length === 0) return panel;
  const headerGroup: FilterGroup = { kind: 'group', combinator: 'and', rules: conditions };
  return {
    kind: 'group',
    combinator: 'and',
    rules: [panel ?? { kind: 'group', combinator: 'and', rules: [] }, headerGroup],
  };
}

function fromCondition(rule: FilterRule, kinds: Record<string, string>): [string, FxHeaderValue] | null {
  if (rule.kind !== 'condition') return null;
  const kind = kinds[rule.field];
  if (kind === 'text' && rule.operator === 'contains' && typeof rule.value === 'string') {
    return [rule.field, { kind: 'text', text: rule.value }];
  }
  if (kind === 'date' && rule.operator === 'between' && Array.isArray(rule.value)) {
    return [rule.field, { kind: 'date', from: rule.value[0] ?? '', to: rule.value[1] ?? '' }];
  }
  if (kind === 'status' && rule.operator === 'in' && Array.isArray(rule.value)) {
    return [rule.field, { kind: 'status', values: rule.value }];
  }
  return null;
}

/**
 * Reads a restored filter (from the address) back into the Filters panel's
 * tree and the header filters: the inverse of `combineFilters`. A tree that
 * doesn't have that shape stays wholly the panel's.
 */
export function splitFilters(
  filter: FilterGroup | null,
  kinds: Record<string, string>,
): { panel: FilterGroup | null; header: FxHeaderFilters } {
  if (
    filter &&
    filter.combinator === 'and' &&
    filter.rules.length === 2 &&
    filter.rules[0].kind === 'group' &&
    filter.rules[1].kind === 'group' &&
    filter.rules[1].combinator === 'and' &&
    filter.rules[1].rules.length > 0
  ) {
    const parsed = filter.rules[1].rules.map((r) => fromCondition(r, kinds));
    const fields = parsed.map((p) => p?.[0]);
    if (parsed.every(Boolean) && new Set(fields).size === fields.length) {
      const panel = filter.rules[0] as FilterGroup;
      return {
        panel: panel.rules.length > 0 ? panel : null,
        header: Object.fromEntries(parsed as [string, FxHeaderValue][]),
      };
    }
  }
  return { panel: filter, header: {} };
}

// ------------------------------------------------------------------- pager

/** Rows-per-page choices under the pager. */
export const FX_PAGE_SIZES = [25, 50, 100] as const;

/**
 * The pager's buttons (playbook "Long lists load in pages"): first, last, and
 * two either side of the current page, with a gap ('gap') between runs.
 * `current` and the result are 1-based.
 */
export function fxPageNumbers(current: number, pageCount: number): (number | 'gap')[] {
  if (pageCount <= 0) return [];
  const pages = new Set<number>([1, pageCount]);
  for (let p = current - 2; p <= current + 2; p++) {
    if (p >= 1 && p <= pageCount) pages.add(p);
  }
  const sorted = Array.from(pages).sort((a, b) => a - b);
  const out: (number | 'gap')[] = [];
  sorted.forEach((p, i) => {
    if (i > 0) {
      const prev = sorted[i - 1];
      // A single missing page is shown rather than hidden behind a gap.
      if (p - prev === 2) out.push(prev + 1);
      else if (p - prev > 2) out.push('gap');
    }
    out.push(p);
  });
  return out;
}

const count = (n: number) => n.toLocaleString('en-US');

/**
 * "Showing 51-100 of 12,340" (every match, not just the loaded page), or
 * "Showing 3 of 3" when it all fits on one page. Hyphen, not the playbook's
 * en dash: SS bans en dashes in every tracked file.
 */
export function fxShowingText(pageIndex: number, pageSize: number, total: number): string {
  if (total <= 0) return 'Showing 0 of 0';
  if (total <= pageSize) return `Showing ${count(total)} of ${count(total)}`;
  const first = pageIndex * pageSize + 1;
  const last = Math.min(total, (pageIndex + 1) * pageSize);
  return `Showing ${count(first)}-${count(last)} of ${count(total)}`;
}
