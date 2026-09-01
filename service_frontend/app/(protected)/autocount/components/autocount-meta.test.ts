import { describe, expect, it } from 'vitest';
import { AC_FIELD_REF_PRESET, presetOptionsForField } from './autocount-meta';

// S5 review BLOCKER 2 (FE half) - foolproof-UI: the Transform picker must
// offer ONLY combinations the server accepts (`mapping.FIELD_REF_TRANSFORMS`,
// `company_service.replace_mapping`), never a ref preset an operator could
// pick and then have the save silently 422 on.

describe('presetOptionsForField', () => {
  it('offers ONLY its own matching ref preset for a *_ref field', () => {
    expect(presetOptionsForField('customer_ref')).toEqual([
      { value: 'ref_customer', label: 'Customer ref' },
    ]);
    expect(presetOptionsForField('supplier_ref')).toEqual([
      { value: 'ref_supplier', label: 'Supplier ref' },
    ]);
    expect(presetOptionsForField('sales_agent_ref')).toEqual([
      { value: 'ref_sales_agent', label: 'Sales agent ref' },
    ]);
  });

  it('never offers ANY ref preset for a non-ref field', () => {
    const options = presetOptionsForField('status');
    expect(options.some((o) => o.value.startsWith('ref_'))).toBe(false);
    // The ordinary presets are all still there.
    expect(options.map((o) => o.value)).toEqual(
      expect.arrayContaining(['text', 'boolean', 'decimal', 'integer', 'date', 'custom']),
    );
  });

  it('never offers a ref preset when no field is chosen yet', () => {
    const options = presetOptionsForField('');
    expect(options.some((o) => o.value.startsWith('ref_'))).toBe(false);
  });

  it('product_ref/warehouse_ref are absent from the field->ref-preset map (line fields are code-generated, never operator-mapped)', () => {
    expect(AC_FIELD_REF_PRESET.product_ref).toBeUndefined();
    expect(AC_FIELD_REF_PRESET.warehouse_ref).toBeUndefined();
  });
});
