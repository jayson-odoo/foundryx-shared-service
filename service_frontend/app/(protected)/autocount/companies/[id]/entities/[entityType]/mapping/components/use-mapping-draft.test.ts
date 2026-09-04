import { act, renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { AutocountMappingRow, AutocountMappingView } from '@/types/autocount';
import { splitMappingRows, useMappingDraft } from './use-mapping-draft';

// ═══════════════════════════════════════════════════════════════════════════
// Final review round (B1) - the FE never sends `isEnabled` at all, so a
// disabled off-preview row resubmitted from the editor 422s server-side (R1
// reproduces through the UI). `AutocountMappingRow.isEnabled` already exists
// on the read side (`types/autocount.ts`); these tests pin it surviving the
// editor's split/write round trip, plus the exact `lineRows` tri-state
// `writeRowsForSave()` must produce.
// ═══════════════════════════════════════════════════════════════════════════

function headerRow(overrides: Partial<AutocountMappingRow> = {}): AutocountMappingRow {
  return {
    sourcePath: 'DocNo',
    transform: 'string',
    formula: null,
    sorentoField: 'so_number',
    canonicalField: 'so_number',
    scope: 'header',
    isRequired: true,
    isEnabled: true,
    ...overrides,
  };
}

function lineRow(overrides: Partial<AutocountMappingRow> = {}): AutocountMappingRow {
  return {
    sourcePath: 'discount',
    transform: 'decimal',
    formula: null,
    sorentoField: 'discount',
    canonicalField: 'discount',
    scope: 'line',
    isRequired: false,
    isEnabled: true,
    ...overrides,
  };
}

describe('splitMappingRows keeps isEnabled', () => {
  it('carries a disabled row into the deliverable set with isEnabled intact', () => {
    const rows: AutocountMappingRow[] = [
      headerRow({ isEnabled: true }),
      headerRow({ sourcePath: 'Remark', sorentoField: 'internal_note', canonicalField: 'internal_note', isEnabled: false }),
    ];
    const { deliverable } = splitMappingRows(rows, 'header');
    const disabled = deliverable.find((r) => r.sorentoField === 'internal_note');
    expect(disabled).toBeDefined();
    expect(disabled?.isEnabled).toBe(false);
    const enabled = deliverable.find((r) => r.sorentoField === 'so_number');
    expect(enabled?.isEnabled).toBe(true);
  });
});

function masterView(): AutocountMappingView {
  return {
    entityType: 'supplier',
    rows: [headerRow()],
    sorentoFields: [{ field: 'so_number', required: true }],
    acFields: ['DocNo'],
    lineSorentoFields: [],
    lineAcFields: [],
  };
}

function documentView(lineRows: AutocountMappingRow[]): AutocountMappingView {
  return {
    entityType: 'sales_order',
    rows: [
      headerRow(),
      ...lineRows,
    ],
    sorentoFields: [{ field: 'so_number', required: true }],
    acFields: ['DocNo'],
    lineSorentoFields: [
      { field: 'source_ref', required: true },
      { field: 'discount', required: false },
    ],
    lineAcFields: ['DtlKey', 'discount'],
  };
}

describe('writeRowsForSave preserves isEnabled and the lineRows tri-state', () => {
  it('a master/GRN entity (no line targets) never carries a lineRows key', () => {
    const { result } = renderHook(() => useMappingDraft(masterView()));
    const body = result.current.writeRowsForSave();
    expect(body.lineRows).toBeUndefined();
    expect(body.rows[0]?.isEnabled).toBe(true);
  });

  it('a document entity with an emptied line draft sends lineRows: []', () => {
    const { result } = renderHook(() => useMappingDraft(documentView([
      lineRow({ sourcePath: 'DtlKey', sorentoField: 'source_ref', canonicalField: 'source_ref', isRequired: true }),
    ])));
    // Clear the one line row the same way the editor's remove button does.
    act(() => {
      result.current.line?.onRemoveRow(0);
    });
    const body = result.current.writeRowsForSave();
    expect(body.lineRows).toEqual([]);
  });

  it('a document entity with a populated line draft preserves isEnabled per row (header AND line)', () => {
    const { result } = renderHook(() => useMappingDraft(documentView([
      lineRow({ sourcePath: 'DtlKey', sorentoField: 'source_ref', canonicalField: 'source_ref', isRequired: true, isEnabled: true }),
      lineRow({ sourcePath: 'discount', sorentoField: 'discount', canonicalField: 'discount', isEnabled: false }),
    ])));
    const body = result.current.writeRowsForSave();
    expect(body.lineRows).toBeDefined();
    expect(body.rows[0]?.isEnabled).toBe(true);
    const disabledLine = body.lineRows?.find((r) => r.sorentoField === 'discount');
    const enabledLine = body.lineRows?.find((r) => r.sorentoField === 'source_ref');
    expect(disabledLine?.isEnabled).toBe(false);
    expect(enabledLine?.isEnabled).toBe(true);
  });
});
