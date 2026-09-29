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
  AC_DOC_FEED_KEYS,
  AC_HTTP_ENTITY_TYPES,
  AC_HTTP_ONLY_ENTITY_TYPES,
  AC_NEW_MASTER_ENTITY_TYPES,
  AC_SQL_DB_ENTITY_TYPES,
  entitiesForSourceKind,
  isHttpOnlyEntity,
  sourceKindLabel,
} from './autocount-meta';

describe('AC_SQL_DB_ENTITY_TYPES (AC-01-17)', () => {
  it('is exactly the eleven sql_db entities - customer + supplier + brand included, GRN absent', () => {
    // sprint-5/08 S4 (AC-08-31) added `brand` - was ten before that commit
    // (this literal went stale until sprint-5/08 review round 1).
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
      'brand',
    ]);
    expect(AC_SQL_DB_ENTITY_TYPES).not.toContain('goods_received_note');
  });

  it('is a strict superset of the API company\'s seven (regression pin)', () => {
    for (const t of AC_NEW_MASTER_ENTITY_TYPES) expect(AC_SQL_DB_ENTITY_TYPES).toContain(t);
    expect(AC_NEW_MASTER_ENTITY_TYPES).toHaveLength(7);
  });

  it('entitiesForSourceKind picks the list by company kind', () => {
    // fix/autocount-add-http-only-entity-on-db-company - a `db` company's
    // list is the sql_db set PLUS the HTTP-only entities (stock_balance) -
    // this already works server-side (`_update_http_task` runs before the
    // "DB company reads only its own connection" rule), so foolproof-UI now
    // offers it. `api`/`http` are untouched.
    // sprint-5/14 section 11 (AC-14-47): `branch` is HTTP-only too, so a db
    // company's list is the sql_db set PLUS every HTTP-only entity.
    expect(entitiesForSourceKind('db')).toEqual([...AC_SQL_DB_ENTITY_TYPES, ...AC_HTTP_ONLY_ENTITY_TYPES]);
    expect(entitiesForSourceKind('db')).toEqual(expect.arrayContaining(['stock_balance', 'branch']));
    expect(entitiesForSourceKind('api')).toBe(AC_NEW_MASTER_ENTITY_TYPES);
    expect(entitiesForSourceKind('http')).toBe(AC_HTTP_ENTITY_TYPES);
  });
});

describe('AC_HTTP_ONLY_ENTITY_TYPES (fix/autocount-add-http-only-entity-on-db-company)', () => {
  it('is exactly the HTTP entities with no sql_db variant - stock_balance and branch (AC-14-47)', () => {
    expect([...AC_HTTP_ONLY_ENTITY_TYPES].sort()).toEqual(['branch', 'stock_balance']);
  });

  it('every other HTTP entity is also SQL-extractable', () => {
    for (const t of AC_HTTP_ENTITY_TYPES) {
      if (t === 'stock_balance' || t === 'branch') continue;
      expect(AC_SQL_DB_ENTITY_TYPES).toContain(t);
    }
  });

  it('isHttpOnlyEntity', () => {
    expect(isHttpOnlyEntity('stock_balance')).toBe(true);
    expect(isHttpOnlyEntity('branch')).toBe(true);
    expect(isHttpOnlyEntity('product')).toBe(false);
    expect(isHttpOnlyEntity('goods_received_note')).toBe(false);
  });
});

describe('AC_HTTP_ENTITY_TYPES (AC-08-18)', () => {
  it('is exactly the six confirmed open-API masters plus stock_balance (sprint-5/10, AC-10-40) plus branch (sprint-5/14, AC-14-47)', () => {
    expect([...AC_HTTP_ENTITY_TYPES].sort()).toEqual(
      [
        'product',
        'customer',
        'warehouse',
        'product_category',
        'brand',
        'unit_of_measure',
        'stock_balance',
        'branch',
      ].sort(),
    );
  });

  it('branch is an HTTP entity but never a sql_db one (AC-14-47)', () => {
    expect(AC_HTTP_ENTITY_TYPES).toContain('branch');
    expect(AC_SQL_DB_ENTITY_TYPES).not.toContain('branch');
    expect(AC_HTTP_ONLY_ENTITY_TYPES).toContain('branch');
    expect(entitiesForSourceKind('http')).toContain('branch');
    expect(entitiesForSourceKind('api')).not.toContain('branch');
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

describe('AC_DOC_FEED_KEYS (AC-14-46/47, plan 14 section 11)', () => {
  it('has exactly the two document feeds - branches left the doc feed and became an entity', () => {
    expect(AC_DOC_FEED_KEYS).toEqual(['delivery_orders', 'goods_receive_notes']);
    expect(AC_DOC_FEED_KEYS).toHaveLength(2);
    expect(AC_DOC_FEED_KEYS).not.toContain('branches');
  });
});
