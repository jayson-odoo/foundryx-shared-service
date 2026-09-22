import { describe, expect, it } from 'vitest';
import { ApiError } from '@/lib/api-client';
import type {
  AutocountMappingResetPreview,
  AutocountMappingRow,
  AutocountMappingUpdate,
  AutocountMappingView,
} from '@/types/autocount';
import { isMappingResetPreview, isMappingResetPreviewEmpty } from '@/types/autocount';
import {
  computeMappingResetDiff,
  mockAutocountService as service,
  withPhase1MappingResetMock,
} from './autocount-service.mock';

/**
 * Mapping preset reset (sprint-5/12, Group B - AC-12-10..24). `computeMapping
 * ResetDiff` is tested directly with hand-built inputs (every AC-12-20 state,
 * no service round trip); `mockAutocountService`/`withPhase1MappingResetMock`
 * are tested through the service boundary the UI actually calls.
 */

function row(overrides: Partial<AutocountMappingRow> = {}): AutocountMappingRow {
  return {
    sourcePath: 'ItemCode',
    transform: 'string',
    formula: null,
    sorentoField: 'code',
    canonicalField: 'code',
    scope: 'header',
    isRequired: true,
    isEnabled: true,
    ...overrides,
  };
}

const TEST_PRESET = {
  label: 'Test preset',
  rows: [
    { sourcePath: 'ItemCode', canonicalField: 'code', transform: 'string', formula: null, required: true, enabled: true },
    { sourcePath: 'Description', canonicalField: 'name', transform: 'string', formula: null, required: false, enabled: true },
    {
      sourcePath: 'Description',
      canonicalField: 'description',
      transform: 'string',
      formula: 'trim(if(default(Desc2, "") != "", concat(Description, " ", Desc2), Description))',
      required: false,
      enabled: true,
    },
    // Withheld by the preset itself, regardless of column presence.
    { sourcePath: 'BaseUOM', canonicalField: 'uom_code', transform: 'string', formula: null, required: false, enabled: false },
    // Not in the task's current preview columns.
    { sourcePath: 'BaseUOMPrice', canonicalField: 'list_price', transform: 'string', formula: null, required: false, enabled: true },
  ],
};

describe('computeMappingResetDiff (AC-12-12/15)', () => {
  it('classifies added / changed / unchanged, and names the ACTUAL disabled cause per row', () => {
    const current: AutocountMappingRow[] = [
      row({ canonicalField: 'code', sourcePath: 'ItemCode' }), // unchanged
      row({ canonicalField: 'name', sourcePath: 'ItemCode', sorentoField: 'name' }), // changed (source differs)
      // 'description' has no current row -> added
      row({ canonicalField: 'uom_code', sourcePath: 'BaseUOM', sorentoField: 'uom_code', isEnabled: true }), // changed (enabled true -> false)
    ];
    const diff = computeMappingResetDiff(TEST_PRESET, current, ['ItemCode', 'Description', 'BaseUOM']);

    const byField = new Map(diff.rows.map((r) => [r.canonicalField, r]));
    expect(byField.get('code')?.change).toBe('unchanged');
    expect(byField.get('name')?.change).toBe('changed');
    expect(byField.get('description')?.change).toBe('added');

    // Preset-withheld: disabled regardless of the column being present, and
    // it says SO - claiming "column not returned" here would be a lie
    // (`BaseUOM` IS in the previewed columns above). UAC amendment
    // 2026-09-22.
    const uom = byField.get('uom_code')!;
    expect(uom.change).toBe('changed');
    expect(uom.enabled).toBe(false);
    expect(uom.disabledReason).toBe('withheld by the preset');

    // Missing from the task's current preview columns: the OTHER cause.
    const listPrice = byField.get('list_price')!;
    expect(listPrice.change).toBe('added');
    expect(listPrice.enabled).toBe(false);
    expect(listPrice.disabledReason).toBe('column not returned by the source');

    // A row every enabled column is present for carries no disabledReason.
    expect(byField.get('code')?.disabledReason).toBeUndefined();
  });

  it('un-previewed columns (availableColumns=[]) seed every non-preset-disabled row enabled', () => {
    const diff = computeMappingResetDiff(TEST_PRESET, [], []);
    const byField = new Map(diff.rows.map((r) => [r.canonicalField, r]));
    expect(byField.get('list_price')?.enabled).toBe(true);
    expect(byField.get('list_price')?.disabledReason).toBeUndefined();
    // Still withheld by the preset's own flag - and says so.
    expect(byField.get('uom_code')?.enabled).toBe(false);
    expect(byField.get('uom_code')?.disabledReason).toBe('withheld by the preset');
  });

  it('a preset-withheld row whose column is ALSO missing reports the withholding, not the column', () => {
    // `BaseUOM` is deliberately absent from the previewed columns here: both
    // causes apply, and the row must not tell the operator to add a lookup
    // that would change nothing.
    const diff = computeMappingResetDiff(TEST_PRESET, [], ['ItemCode', 'Description']);
    const uom = diff.rows.find((r) => r.canonicalField === 'uom_code')!;
    expect(uom.enabled).toBe(false);
    expect(uom.disabledReason).toBe('withheld by the preset');
  });

  it('a current row whose canonical field the preset drops lands under "removed", never silently dropped', () => {
    const current: AutocountMappingRow[] = [
      row({ canonicalField: 'code' }),
      row({ canonicalField: 'brand_code', sourcePath: 'ItemBrand', sorentoField: 'brand_code' }),
    ];
    const diff = computeMappingResetDiff(TEST_PRESET, current, ['ItemCode']);
    expect(diff.removed).toEqual([
      { canonicalField: 'brand_code', sourcePath: 'ItemBrand', transform: 'string', formula: null },
    ]);
  });

  it('a provenance row (sorentoField null) is never counted as current or removed', () => {
    const current: AutocountMappingRow[] = [
      row({ canonicalField: 'code' }),
      row({ canonicalField: 'last_modified', sorentoField: null }),
    ];
    const diff = computeMappingResetDiff(TEST_PRESET, current, ['ItemCode']);
    expect(diff.removed).toEqual([]);
  });

  it('an empty diff (mapping already matches the preset) is empty per isMappingResetPreviewEmpty', () => {
    const current: AutocountMappingRow[] = TEST_PRESET.rows.map((p) =>
      row({
        canonicalField: p.canonicalField,
        sourcePath: p.sourcePath,
        transform: p.transform,
        formula: p.formula,
        isEnabled: p.enabled,
        isRequired: p.required,
      }),
    );
    const diff = computeMappingResetDiff(TEST_PRESET, current, ['ItemCode', 'Description', 'BaseUOM', 'BaseUOMPrice']);
    expect(diff.rows.every((r) => r.change === 'unchanged')).toBe(true);
    expect(diff.removed).toEqual([]);
    expect(isMappingResetPreviewEmpty(diff)).toBe(true);
  });
});

describe('mockAutocountService.resetMappingToPreset (Vitest double)', () => {
  it('422s "No preset is registered for this entity." for an entity with none', async () => {
    await expect(
      service.resetMappingToPreset('company-1', 'goods_received_note', { dryRun: true }),
    ).rejects.toMatchObject({ message: 'No preset is registered for this entity.', status: 422 });
  });

  it('a dry run for a real preset entity (product) returns a preview, writes nothing', async () => {
    const before = await service.getMapping('company-http', 'product');
    const result = await service.resetMappingToPreset('company-http', 'product', { dryRun: true });
    expect(isMappingResetPreview(result)).toBe(true);
    const after = await service.getMapping('company-http', 'product');
    expect(after.rows).toEqual(before.rows);
  });

  it('apply (dryRun=false) returns the fresh mapping view with hasPreset carried', async () => {
    const result = await service.resetMappingToPreset('company-http', 'product', { dryRun: false });
    expect(isMappingResetPreview(result)).toBe(false);
    const view = result as AutocountMappingView;
    expect(view.hasPreset).toBe(true);
    expect(view.rows.map((r) => r.canonicalField)).toEqual(
      expect.arrayContaining(['code', 'name', 'description', 'list_price']),
    );
  });
});

describe('withPhase1MappingResetMock (S1 overlay bound by autocount-service.ts)', () => {
  function fakeReal(view: AutocountMappingView) {
    const calls: string[] = [];
    const written: string[][] = [];
    return {
      calls,
      written,
      service: {
        async getMapping() {
          calls.push('getMapping');
          return view;
        },
        async updateMapping(_companyId: string, _entityType: string, input: AutocountMappingUpdate) {
          calls.push('updateMapping');
          written.push(input.rows.map((r) => r.sorentoField));
          return { ...view, rows: [] };
        },
        // Every other method throws if called - the overlay must delegate,
        // never reimplement, anything but hasPreset + resetMappingToPreset.
      } as unknown as Parameters<typeof withPhase1MappingResetMock>[0],
    };
  }

  const BASE_VIEW: AutocountMappingView = {
    entityType: 'product',
    rows: [],
    // The server's OWN accepted catalog - deliberately WITHOUT
    // `is_discontinued` (captured by the preset, absent from
    // `CanonicalProduct.SINK_FIELDS`, BL-SS-260), which is exactly the row
    // the overlay's PUT has to leave out.
    sorentoFields: [
      { field: 'code', required: true },
      { field: 'name', required: true },
      { field: 'description', required: false },
      { field: 'uom_code', required: false },
      { field: 'list_price', required: false },
      { field: 'category_code', required: false },
      { field: 'brand_code', required: false },
      { field: 'is_active', required: true },
    ],
    acFields: ['ItemCode'],
    lineSorentoFields: [],
    lineAcFields: [],
  };

  it('getMapping gains a client-side hasPreset for a registered entity', async () => {
    const { service: real } = fakeReal(BASE_VIEW);
    const overlaid = withPhase1MappingResetMock(real);
    const view = await overlaid.getMapping('c1', 'product');
    expect(view.hasPreset).toBe(true);
  });

  it('getMapping never overrides a server-supplied hasPreset', async () => {
    const { service: real } = fakeReal({ ...BASE_VIEW, hasPreset: false });
    const overlaid = withPhase1MappingResetMock(real);
    const view = await overlaid.getMapping('c1', 'product');
    expect(view.hasPreset).toBe(false);
  });

  it('resetMappingToPreset 422s for an unregistered entity without ever calling real', async () => {
    const { calls, service: real } = fakeReal(BASE_VIEW);
    const overlaid = withPhase1MappingResetMock(real);
    await expect(
      overlaid.resetMappingToPreset('c1', 'goods_received_note', { dryRun: true }),
    ).rejects.toBeInstanceOf(ApiError);
    expect(calls).toEqual([]);
  });

  it('dryRun=true reads the REAL current mapping and returns a diff, calling no write', async () => {
    const { calls, service: real } = fakeReal(BASE_VIEW);
    const overlaid = withPhase1MappingResetMock(real);
    const result = await overlaid.resetMappingToPreset('c1', 'product', { dryRun: true });
    expect(isMappingResetPreview(result)).toBe(true);
    expect(calls).toEqual(['getMapping']);
  });

  it('dryRun=false applies through the REAL updateMapping and returns hasPreset: true', async () => {
    const { calls, written, service: real } = fakeReal(BASE_VIEW);
    const overlaid = withPhase1MappingResetMock(real);
    const result = await overlaid.resetMappingToPreset('c1', 'product', { dryRun: false });
    expect(isMappingResetPreview(result)).toBe(false);
    expect((result as AutocountMappingView).hasPreset).toBe(true);
    expect(calls).toEqual(['getMapping', 'updateMapping']);
    // PHASE 1 ONLY (BL-SS-260): the PUT carries the accepted subset - the
    // preset's `is_discontinued` row is not a Sorento-accepted target, so the
    // save gate would 422 the whole apply. The DRY RUN still shows it.
    expect(written[0]).not.toContain('is_discontinued');
    expect(written[0]).toContain('list_price');
    const preview = (await overlaid.resetMappingToPreset('c1', 'product', {
      dryRun: true,
    })) as AutocountMappingResetPreview;
    expect(preview.rows.map((r) => r.canonicalField)).toContain('is_discontinued');
  });
});
