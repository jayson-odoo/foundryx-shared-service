import { describe, expect, it } from 'vitest';
import {
  DIFF_IGNORED_FIELDS,
  diffForDisplay,
  formatDiffValue,
  humanizeFieldKey,
  parseRecordDiff,
} from './autocount-diff';

describe('parseRecordDiff', () => {
  it('returns no changes for a null diff', () => {
    expect(parseRecordDiff(null)).toEqual({ isNew: false, changes: [] });
  });

  it('returns no changes for an empty diff - nothing changed is not everything changed', () => {
    expect(parseRecordDiff({})).toEqual({ isNew: false, changes: [] });
  });

  it('flags a first-seen record via the __new__ sentinel', () => {
    expect(parseRecordDiff({ __new__: true })).toEqual({ isNew: true, changes: [] });
  });

  it('maps each changed field to before → after', () => {
    const result = parseRecordDiff({
      total: { from: '100.00', to: '120.00' },
      supplier_name: { from: 'Acme', to: 'Acme Sdn Bhd' },
    });
    expect(result.isNew).toBe(false);
    expect(result.changes).toEqual([
      { field: 'supplier_name', from: 'Acme', to: 'Acme Sdn Bhd' },
      { field: 'total', from: '100.00', to: '120.00' },
    ]);
  });

  it('never renders an unchanged field as a change', () => {
    // The server omits unchanged fields; nothing client-side re-derives them.
    const result = parseRecordDiff({ total: { from: '100.00', to: '120.00' } });
    expect(result.changes.map((c) => c.field)).toEqual(['total']);
    expect(result.changes.map((c) => c.field)).not.toContain('supplier_name');
  });

  it('skips malformed entries rather than inventing a change', () => {
    const result = parseRecordDiff({ total: 'not-a-change' });
    expect(result.changes).toEqual([]);
  });

  it('preserves a null-to-value change (from is legitimately null)', () => {
    const result = parseRecordDiff({ description: { from: null, to: 'Urgent' } });
    expect(result.changes).toEqual([
      { field: 'description', from: null, to: 'Urgent' },
    ]);
  });
});

describe('diffForDisplay', () => {
  it('expands a new record’s canonical payload as nothing → value', () => {
    const result = diffForDisplay(
      { __new__: true },
      { doc_no: 'GRN-001', total: '250.00', supplier_name: '' },
    );
    expect(result.isNew).toBe(true);
    expect(result.changes).toEqual([
      { field: 'doc_no', from: undefined, to: 'GRN-001' },
      { field: 'total', from: undefined, to: '250.00' },
    ]);
  });

  it('does NOT re-add last_modified - it moves on every fetch by definition', () => {
    const result = diffForDisplay(
      { __new__: true },
      { doc_no: 'GRN-001', last_modified: '2026-07-01T00:00:00Z' },
    );
    expect(result.changes.map((c) => c.field)).toEqual(['doc_no']);
    expect(DIFF_IGNORED_FIELDS.has('last_modified')).toBe(true);
  });

  it('drops every backend-ignored field on the new-record path', () => {
    const canonical: Record<string, unknown> = { doc_no: 'GRN-001' };
    for (const key of DIFF_IGNORED_FIELDS) canonical[key] = 'x';
    const result = diffForDisplay({ __new__: true }, canonical);
    expect(result.changes.map((c) => c.field)).toEqual(['doc_no']);
  });

  it('leaves a normal diff untouched', () => {
    const diff = { total: { from: '1', to: '2' } };
    expect(diffForDisplay(diff, { total: '2', doc_no: 'X' }).changes).toEqual([
      { field: 'total', from: '1', to: '2' },
    ]);
  });

  it('yields no changes for a new record with no canonical payload', () => {
    expect(diffForDisplay({ __new__: true }, null)).toEqual({
      isNew: true,
      changes: [],
    });
  });
});

describe('formatDiffValue', () => {
  it('renders an em dash for nothing', () => {
    expect(formatDiffValue(null)).toEqual({ kind: 'empty', text: '-' });
    expect(formatDiffValue(undefined)).toEqual({ kind: 'empty', text: '-' });
    expect(formatDiffValue('')).toEqual({ kind: 'empty', text: '-' });
  });

  it('renders booleans as Yes/No', () => {
    expect(formatDiffValue(false)).toEqual({ kind: 'scalar', text: 'No' });
    expect(formatDiffValue(true)).toEqual({ kind: 'scalar', text: 'Yes' });
  });

  it('keeps a zero as a scalar, not as empty', () => {
    expect(formatDiffValue(0)).toEqual({ kind: 'scalar', text: '0' });
  });

  it('marks objects and arrays structured so they get their own block', () => {
    expect(formatDiffValue([{ qty: 1 }]).kind).toBe('structured');
    expect(formatDiffValue({ a: 1 }).kind).toBe('structured');
  });

  it('renders an empty collection as nothing, not as a bare [] block', () => {
    expect(formatDiffValue([])).toEqual({ kind: 'empty', text: '-' });
    expect(formatDiffValue({})).toEqual({ kind: 'empty', text: '-' });
  });
});

describe('humanizeFieldKey', () => {
  it('humanizes snake_case', () => {
    expect(humanizeFieldKey('supplier_name')).toBe('Supplier name');
  });

  it('humanizes camelCase', () => {
    expect(humanizeFieldKey('supplierName')).toBe('Supplier name');
  });

  it('humanizes a canonical entity key', () => {
    expect(humanizeFieldKey('goods_received_note')).toBe('Goods received note');
  });
});
