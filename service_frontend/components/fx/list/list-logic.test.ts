import { describe, expect, it } from 'vitest';
import type { FilterFieldDef, FilterGroup } from '@/types/resource';
import {
  FX_COLUMN_CAP,
  FX_LONG_CAP,
  combineFilters,
  fxHeaderFilterKind,
  fxPageNumbers,
  fxShowingText,
  planSmartColumns,
  splitFilters,
} from './list-logic';

describe('planSmartColumns (Smart view info lines)', () => {
  const cols = [
    { id: 'select', need: 40, fixed: true },
    { id: 'name', need: 150 },
    { id: 'title', need: 600, long: true },
    { id: 'salesperson', need: 120 },
    { id: 'branch', need: 90 },
  ];

  it('keeps every column and spreads spare width evenly when they fit', () => {
    const plan = planSmartColumns(cols, 1000);
    expect(plan.infoLines).toEqual([]);
    // 40 + 150 + 320 + 120 + 90 = 720, 280 spare over 4 data columns.
    expect(plan.widths).toEqual({ select: 40, name: 220, title: 390, salesperson: 190, branch: 160 });
  });

  it('caps long text at the long cap and the rest at the column cap', () => {
    const plan = planSmartColumns(
      [
        { id: 'a', need: 900, long: true },
        { id: 'b', need: 900 },
      ],
      0,
    );
    expect(plan.widths).toEqual({ a: FX_LONG_CAP, b: FX_COLUMN_CAP });
  });

  it('moves the right-most columns into info lines one at a time, in order', () => {
    const plan = planSmartColumns(cols, 560);
    expect(plan.inTable).toEqual(['select', 'name', 'title']);
    expect(plan.infoLines).toEqual(['salesperson', 'branch']);
    expect(plan.tooNarrow).toBe(false);
  });

  it('keeps at least two data columns and says when even they do not fit', () => {
    const plan = planSmartColumns(cols, 200);
    expect(plan.inTable).toEqual(['select', 'name', 'title']);
    expect(plan.tooNarrow).toBe(true);
  });

  it('never moves a fixed column', () => {
    const plan = planSmartColumns(
      [
        { id: 'name', need: 150 },
        { id: 'email', need: 150 },
        { id: 'phone', need: 150 },
        { id: 'actions', need: 48, fixed: true },
      ],
      360,
    );
    expect(plan.inTable).toEqual(['name', 'email', 'actions']);
    expect(plan.infoLines).toEqual(['phone']);
  });

  it('keeps every column while the width is unknown', () => {
    const plan = planSmartColumns(cols, 0);
    expect(plan.infoLines).toEqual([]);
    expect(plan.inTable).toHaveLength(5);
  });
});

describe('fxHeaderFilterKind (filter kinds chosen from values)', () => {
  const text: FilterFieldDef = { field: 'name', label: 'Name', type: 'text' };
  const date: FilterFieldDef = { field: 'createdAt', label: 'Created', type: 'date' };
  const status: FilterFieldDef = {
    field: 'status',
    label: 'Status',
    type: 'enum',
    options: [{ label: 'Active', value: 'active' }],
  };

  it('gives no header filter to a column the list cannot filter', () => {
    expect(fxHeaderFilterKind(undefined, 'text', ['a'])).toBeNull();
  });

  it('reads text, dates and status from the field type', () => {
    expect(fxHeaderFilterKind(text, undefined, ['Alpha'])).toBe('text');
    expect(fxHeaderFilterKind(date, undefined, [])).toBe('date');
    expect(fxHeaderFilterKind(status, undefined, ['active'])).toBe('status');
  });

  it('reads the kind from the values when the field type does not say', () => {
    expect(fxHeaderFilterKind(text, undefined, ['2026-11-05T02:00:00Z', null])).toBeNull();
    expect(fxHeaderFilterKind(text, undefined, [12, 40])).toBeNull();
    expect(fxHeaderFilterKind(text, undefined, ['Tan', 'Lim'])).toBe('text');
  });

  it('follows the page choice when the field supports it', () => {
    expect(fxHeaderFilterKind(text, 'text', [])).toBe('text');
    expect(fxHeaderFilterKind(text, 'status', [])).toBeNull();
    expect(fxHeaderFilterKind(text, 'amount', [])).toBeNull();
  });

  it('respects the operators a field allows', () => {
    expect(fxHeaderFilterKind({ ...date, operators: ['before', 'after'] }, undefined, [])).toBeNull();
    expect(fxHeaderFilterKind({ ...status, options: [] }, undefined, [])).toBeNull();
  });
});

describe('combineFilters / splitFilters', () => {
  const panel: FilterGroup = {
    kind: 'group',
    combinator: 'or',
    rules: [{ kind: 'condition', field: 'email', operator: 'contains', value: 'x' }],
  };
  const kinds = { name: 'text', createdAt: 'date', status: 'status' };

  it('passes the panel filter through untouched with no header filter', () => {
    expect(combineFilters(panel, {})).toBe(panel);
    expect(combineFilters(null, { name: { kind: 'text', text: '  ' } })).toBeNull();
  });

  it('adds the header filters as one AND group and reads them back', () => {
    const header = {
      name: { kind: 'text' as const, text: 'tan' },
      createdAt: { kind: 'date' as const, from: '2026-11-01', to: '2026-11-30' },
      status: { kind: 'status' as const, values: ['active'] },
    };
    const combined = combineFilters(panel, header);
    expect(combined?.rules[1]).toEqual({
      kind: 'group',
      combinator: 'and',
      rules: [
        { kind: 'condition', field: 'name', operator: 'contains', value: 'tan' },
        { kind: 'condition', field: 'createdAt', operator: 'between', value: ['2026-11-01', '2026-11-30'] },
        { kind: 'condition', field: 'status', operator: 'in', value: ['active'] },
      ],
    });
    expect(splitFilters(combined, kinds)).toEqual({ panel, header });
  });

  it('reads a header-only filter back with no panel filter', () => {
    const combined = combineFilters(null, { name: { kind: 'text', text: 'lim' } });
    expect(splitFilters(combined, kinds)).toEqual({
      panel: null,
      header: { name: { kind: 'text', text: 'lim' } },
    });
  });

  it('leaves any other tree to the panel', () => {
    expect(splitFilters(panel, kinds)).toEqual({ panel, header: {} });
  });
});

describe('fxPageNumbers (pager numbers with gaps)', () => {
  it('shows every page of a short list', () => {
    expect(fxPageNumbers(1, 5)).toEqual([1, 2, 3, 4, 5]);
  });

  it('shows first, last and two either side of the current page', () => {
    expect(fxPageNumbers(10, 247)).toEqual([1, 'gap', 8, 9, 10, 11, 12, 'gap', 247]);
  });

  it('fills a one-page gap instead of hiding it', () => {
    expect(fxPageNumbers(4, 20)).toEqual([1, 2, 3, 4, 5, 6, 'gap', 20]);
  });

  it('handles the ends and no pages', () => {
    expect(fxPageNumbers(1, 247)).toEqual([1, 2, 3, 'gap', 247]);
    expect(fxPageNumbers(247, 247)).toEqual([1, 'gap', 245, 246, 247]);
    expect(fxPageNumbers(1, 0)).toEqual([]);
  });
});

describe('fxShowingText', () => {
  it('counts every match with the page range', () => {
    expect(fxShowingText(1, 50, 12340)).toBe('Showing 51-100 of 12,340');
    expect(fxShowingText(246, 50, 12340)).toBe('Showing 12,301-12,340 of 12,340');
  });

  it('drops the range when everything fits', () => {
    expect(fxShowingText(0, 50, 3)).toBe('Showing 3 of 3');
    expect(fxShowingText(0, 50, 0)).toBe('Showing 0 of 0');
  });
});
