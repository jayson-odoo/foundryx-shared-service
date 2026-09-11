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

// Plan sprint-5/01 (AC-01-16/17) - the DB company's entity catalogue + kind labels.
// Plan sprint-5/08 (AC-08-10/18) - the open (http) company kind + entity set.
import {
  AC_HTTP_ENTITY_TYPES,
  AC_NEW_MASTER_ENTITY_TYPES,
  AC_SQL_DB_ENTITY_TYPES,
  entitiesForSourceKind,
  sourceKindLabel,
} from './autocount-meta';

describe('AC_SQL_DB_ENTITY_TYPES (AC-01-17)', () => {
  it('is exactly the ten sql_db entities - customer + supplier included, GRN absent', () => {
    expect(AC_SQL_DB_ENTITY_TYPES).toEqual([
      'customer',
      'supplier',
      'product_category',
      'unit_of_measure',
      'warehouse',
      'product',
      'sales_agent',
      'sales_order',
      'purchase_order',
      'shipping_order',
    ]);
    expect(AC_SQL_DB_ENTITY_TYPES).not.toContain('goods_received_note');
  });

  it('is a strict superset of the API company\'s seven (regression pin)', () => {
    for (const t of AC_NEW_MASTER_ENTITY_TYPES) expect(AC_SQL_DB_ENTITY_TYPES).toContain(t);
    expect(AC_NEW_MASTER_ENTITY_TYPES).toHaveLength(7);
  });

  it('entitiesForSourceKind picks the list by company kind', () => {
    expect(entitiesForSourceKind('db')).toBe(AC_SQL_DB_ENTITY_TYPES);
    expect(entitiesForSourceKind('api')).toBe(AC_NEW_MASTER_ENTITY_TYPES);
    expect(entitiesForSourceKind('http')).toBe(AC_HTTP_ENTITY_TYPES);
  });
});

describe('AC_HTTP_ENTITY_TYPES (AC-08-18)', () => {
  it('is exactly the six confirmed open-API masters', () => {
    expect(AC_HTTP_ENTITY_TYPES).toEqual([
      'product',
      'customer',
      'warehouse',
      'product_category',
      'brand',
      'unit_of_measure',
    ]);
  });
});

describe('sourceKindLabel (AC-01-16, AC-08-10)', () => {
  it('labels the three kinds and humanizes anything else', () => {
    expect(sourceKindLabel('api')).toBe('API (basic auth)');
    expect(sourceKindLabel('http')).toBe('API (no auth)');
    expect(sourceKindLabel('db')).toBe('Database');
    expect(sourceKindLabel('something_else')).toBe('Something else');
  });
});
