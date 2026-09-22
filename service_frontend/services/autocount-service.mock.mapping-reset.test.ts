import { describe, expect, it } from 'vitest';
import type { AutocountMappingRow, AutocountMappingView } from '@/types/autocount';
import { isMappingResetPreview, isMappingResetPreviewEmpty } from '@/types/autocount';
import { computeMappingResetDiff, mockAutocountService as service } from './autocount-service.mock';

/**
 * Mapping preset reset (sprint-5/12, Group B - AC-12-10..24). `computeMapping
 * ResetDiff` is tested directly with hand-built inputs (every AC-12-20 state,
 * no service round trip); `mockAutocountService` is tested through the
 * service boundary. The S1 PHASE 1 MOCK overlay and its own suite are GONE -
 * S2 landed the real route and `autocount-service.ts` binds
 * `realAutocountService` bare.
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

  // sprint-5/12 review round 2 (should-fix 3) - the view's `hasPreset` and
  // the reset double must AGREE: a document view that says `true` must not
  // open the dialog into a 422 the real backend never produces.
  it('a document view that says hasPreset resolves a HEADER-only dry run (sales_order)', async () => {
    const view = await service.getMapping('company-1', 'sales_order');
    expect(view.hasPreset).toBe(true);
    const result = await service.resetMappingToPreset('company-1', 'sales_order', { dryRun: true });
    expect(isMappingResetPreview(result)).toBe(true);
    const preview = result as Exclude<typeof result, AutocountMappingView>;
    expect(preview.label).toBe('AutoCount SO');
    const headerFields = view.rows.filter((r) => r.scope === 'header').map((r) => r.canonicalField);
    const lineFields = new Set(view.rows.filter((r) => r.scope === 'line').map((r) => r.canonicalField));
    expect(preview.rows.map((r) => r.canonicalField)).toEqual(headerFields);
    expect(preview.rows.some((r) => lineFields.has(r.canonicalField))).toBe(false);
    expect(preview.removed).toEqual([]);
  });

  it('a document apply leaves every line row untouched (AC-12-13)', async () => {
    const before = await service.getMapping('company-1', 'sales_order');
    const linesBefore = before.rows.filter((r) => r.scope === 'line');
    expect(linesBefore.length).toBeGreaterThan(0);
    const result = await service.resetMappingToPreset('company-1', 'sales_order', { dryRun: false });
    const after = result as AutocountMappingView;
    expect(after.rows.filter((r) => r.scope === 'line')).toEqual(linesBefore);
    expect(after.rows.filter((r) => r.scope === 'header').map((r) => r.canonicalField)).toEqual(
      before.rows.filter((r) => r.scope === 'header').map((r) => r.canonicalField),
    );
  });
});
