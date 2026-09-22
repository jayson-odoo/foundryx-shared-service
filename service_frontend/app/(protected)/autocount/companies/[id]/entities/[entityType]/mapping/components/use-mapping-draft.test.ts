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
      // NOT 'discount' - final reviewer pass, toWrite now revives a row
      // whose sourcePath already resolves against the current acFields
      // (documentView's lineAcFields is ['DtlKey', 'discount']), so this
      // row's source stays genuinely off-preview to keep testing "isEnabled
      // preserved" rather than accidentally exercising the revive path.
      lineRow({ sourcePath: 'stale_discount', sorentoField: 'discount', canonicalField: 'discount', isEnabled: false }),
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

// ═══════════════════════════════════════════════════════════════════════════
// B1-b (final reviewer pass) - a disabled mapping row (isEnabled=false, e.g.
// after migration 0012's disable-off-preview repair) can never be
// re-enabled from the UI today: fixing its source column leaves
// isEnabled=false and the field silently pushes nothing forever. Contract:
// in `onChangeRow`, a patch that sets `sourcePath` to a column PRESENT in
// the scope's `acFields` revives the row (`isEnabled: true`); a patch to a
// column NOT in `acFields` leaves it disabled - the operator sees it stay
// greyed until they pick a real column.
// ═══════════════════════════════════════════════════════════════════════════
describe('onChangeRow revives a disabled row once its source column resolves (B1-b)', () => {
  it('fixing sourcePath to a column present in acFields flips isEnabled back to true', () => {
    const { result } = renderHook(() => useMappingDraft(documentView([
      lineRow({
        sourcePath: 'stale_col', sorentoField: 'discount', canonicalField: 'discount',
        isEnabled: false,
      }),
    ])));
    const idx = result.current.line?.rows.findIndex((r) => r.sorentoField === 'discount') ?? -1;
    expect(idx).toBeGreaterThanOrEqual(0);
    act(() => {
      // 'discount' IS in documentView's lineAcFields - a real, pickable column.
      result.current.line?.onChangeRow(idx, { sourcePath: 'discount' });
    });
    const row = result.current.line?.rows[idx];
    expect(row?.isEnabled).toBe(true);
  });

  it('fixing sourcePath to a column NOT in acFields leaves the row disabled', () => {
    const { result } = renderHook(() => useMappingDraft(documentView([
      lineRow({
        sourcePath: 'stale_col', sorentoField: 'discount', canonicalField: 'discount',
        isEnabled: false,
      }),
    ])));
    const idx = result.current.line?.rows.findIndex((r) => r.sorentoField === 'discount') ?? -1;
    act(() => {
      // 'still_bogus' is NOT in documentView's lineAcFields (['DtlKey', 'discount']).
      result.current.line?.onChangeRow(idx, { sourcePath: 'still_bogus' });
    });
    const row = result.current.line?.rows[idx];
    expect(row?.isEnabled).toBe(false);
  });

  it('writeRowsForSave() emits the revived flag after a fixed sourcePath', () => {
    const { result } = renderHook(() => useMappingDraft(documentView([
      lineRow({
        sourcePath: 'stale_col', sorentoField: 'discount', canonicalField: 'discount',
        isEnabled: false,
      }),
    ])));
    const idx = result.current.line?.rows.findIndex((r) => r.sorentoField === 'discount') ?? -1;
    act(() => {
      result.current.line?.onChangeRow(idx, { sourcePath: 'discount' });
    });
    const body = result.current.writeRowsForSave();
    const revived = body.lineRows?.find((r) => r.sorentoField === 'discount');
    expect(revived?.isEnabled).toBe(true);
  });

  it('writeRowsForSave() does NOT revive a row STILL disabled in the draft, even when its sourcePath resolves (AC-12-26)', () => {
    // sprint-5/12 (AC-12-26) - THE ASSERTION IS INVERTED, deliberately.
    // This case used to pin the sprint-5/02 B1 save-time revive: a row
    // whose column had returned to the preview was re-enabled by the act of
    // saving. That is an ambiguous auto-derived action once a row can be
    // disabled for a SECOND reason - a preset withholding it - and it
    // silently re-enabled `uom_code` on every save, which AC-10-74
    // withholds precisely to prevent. A save now sends the stored flag
    // verbatim; the operator turns the row on with its own Enabled switch
    // (AC-12-25) or by re-picking the source column (the B1-b test above,
    // still green).
    const { result } = renderHook(() => useMappingDraft(documentView([
      lineRow({
        sourcePath: 'discount', sorentoField: 'discount', canonicalField: 'discount',
        isEnabled: false,
      }),
    ])));
    const body = result.current.writeRowsForSave();
    const written = body.lineRows?.find((r) => r.sorentoField === 'discount');
    expect(written?.isEnabled).toBe(false);
  });

  it('writeRowsForSave() sends an operator-enabled row as enabled (AC-12-25/26)', () => {
    const { result } = renderHook(() => useMappingDraft(documentView([
      lineRow({
        sourcePath: 'discount', sorentoField: 'discount', canonicalField: 'discount',
        isEnabled: false,
      }),
    ])));
    const idx = result.current.line?.rows.findIndex((r) => r.sorentoField === 'discount') ?? -1;
    act(() => {
      // Exactly what the row's Enabled switch dispatches - nothing else.
      result.current.line?.onChangeRow(idx, { isEnabled: true });
    });
    const body = result.current.writeRowsForSave();
    expect(body.lineRows?.find((r) => r.sorentoField === 'discount')?.isEnabled).toBe(true);
  });

  it('toggling Enabled OFF round-trips as false even when the column is previewed (AC-12-26)', () => {
    // The `uom_code` shape: the column IS in the preview, the operator
    // switches the row off, and the save must respect that.
    const { result } = renderHook(() => useMappingDraft(documentView([
      lineRow({
        sourcePath: 'discount', sorentoField: 'discount', canonicalField: 'discount',
        isEnabled: true,
      }),
    ])));
    const idx = result.current.line?.rows.findIndex((r) => r.sorentoField === 'discount') ?? -1;
    act(() => {
      result.current.line?.onChangeRow(idx, { isEnabled: false });
    });
    const body = result.current.writeRowsForSave();
    expect(body.lineRows?.find((r) => r.sorentoField === 'discount')?.isEnabled).toBe(false);
  });
});
