import { describe, expect, it } from 'vitest';
import { AC_TRANSFORMS } from '@/app/(protected)/autocount/components/autocount-meta';
import { TRANSFORM_OUTPUT_SHAPE, isListTransform } from '@/lib/autocount-formula';
import { mockAutocountService as service } from './autocount-service.mock';

/**
 * Sprint-5/06 S0 (AC-06-21) - PHASE 1 MOCK coverage for the PO/SPO/SPO line
 * linkage targets, before any backend code exists: the transform picker
 * offers `string_list`, the formula type map treats it as a list output, and
 * the mock PO/SPO line catalogs carry the ten new targets (eight input
 * fields + `from_so_numbers` + `from_po_number`) named in the UAC
 * Definitions - the SO line catalog carries none of them.
 */

// The UAC Definitions block, verbatim: the eight "input field" names + the
// two wire fields the operator maps directly.
const LINE_LINKAGE_TARGETS = [
  'from_so_doc_key',
  'from_so_line_key',
  'from_so_external_db',
  'from_so_external_doc_key',
  'from_so_external_doc_no',
  'from_so_external_line_key',
  'from_po_doc_key',
  'from_po_line_key',
  'from_so_numbers',
  'from_po_number',
];

describe('transform picker offers string_list (AC-06-21)', () => {
  it('AC_TRANSFORMS carries string_list labelled "Comma-separated list"', () => {
    expect(AC_TRANSFORMS).toContainEqual({ value: 'string_list', label: 'Comma-separated list' });
  });
});

describe('the formula type map treats string_list as a list output (AC-06-21)', () => {
  it('string_list is a list, not a scalar', () => {
    expect(TRANSFORM_OUTPUT_SHAPE.string_list).toBe('list');
    expect(isListTransform('string_list')).toBe(true);
  });

  it('every other known transform stays a scalar (never invented for it)', () => {
    for (const transform of ['string', 'bool', 't_f_bool', 'int', 'decimal', 'date', 'datetime', 'slash_datetime']) {
      expect(isListTransform(transform)).toBe(false);
    }
  });
});

describe('mock PO/SPO line catalogs carry the ten line-linkage targets, SO carries none (AC-06-21)', () => {
  it('purchase_order line catalog offers all ten targets', async () => {
    const view = await service.getMapping('company-1', 'purchase_order');
    const fields = new Set(view.lineSorentoFields.map((f) => f.field));
    for (const target of LINE_LINKAGE_TARGETS) {
      expect(fields.has(target)).toBe(true);
    }
  });

  it('shipping_order line catalog offers all ten targets', async () => {
    const view = await service.getMapping('company-1', 'shipping_order');
    const fields = new Set(view.lineSorentoFields.map((f) => f.field));
    for (const target of LINE_LINKAGE_TARGETS) {
      expect(fields.has(target)).toBe(true);
    }
  });

  it('sales_order line catalog offers none of the ten targets', async () => {
    const view = await service.getMapping('company-1', 'sales_order');
    const fields = new Set(view.lineSorentoFields.map((f) => f.field));
    for (const target of LINE_LINKAGE_TARGETS) {
      expect(fields.has(target)).toBe(false);
    }
  });

  it('the mapped from_so_numbers row on PO/SPO uses the string_list transform', async () => {
    for (const entityType of ['purchase_order', 'shipping_order']) {
      const view = await service.getMapping('company-1', entityType);
      const row = view.rows.find((r) => r.sorentoField === 'from_so_numbers');
      expect(row?.transform).toBe('string_list');
    }
  });
});
