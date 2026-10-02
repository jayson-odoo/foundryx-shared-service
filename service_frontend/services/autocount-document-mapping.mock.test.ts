import { describe, expect, it } from 'vitest';
import { ApiError } from '@/lib/api-client';
import { mockAutocountService as service } from './autocount-service.mock';

/**
 * The document mapping mock (sprint-5/02 S1) IS the phase-2 backend spec:
 * scope-tagged rows, the SO/PO/SPO preset seed, line aggregates + the
 * default status formula, and Simulate over header + lines.
 */
describe('mock document mapping (sprint-5/02)', () => {
  it('getMapping carries both header and line scopes for a document entity (AC-02-01/02)', async () => {
    const view = await service.getMapping('company-1', 'sales_order');
    expect(view.lineSorentoFields.length).toBeGreaterThan(0);
    expect(view.lineAcFields.length).toBeGreaterThan(0);
    const scopes = new Set(view.rows.map((r) => r.scope));
    expect(scopes).toEqual(new Set(['header', 'line']));
  });

  it('a master entity carries empty line scopes - single section unchanged (AC-02-18)', async () => {
    const view = await service.getMapping('company-1', 'customer');
    expect(view.lineSorentoFields).toEqual([]);
    expect(view.lineAcFields).toEqual([]);
    expect(view.rows.every((r) => r.scope === 'header')).toBe(true);
  });

  it('a header re-map never touches line rows and vice versa (AC-02-01)', async () => {
    const view = await service.getMapping('company-1', 'sales_order');
    const lineRows = view.rows.filter((r) => r.scope === 'line' && r.sorentoField);
    const saved = await service.updateMapping('company-1', 'sales_order', {
      rows: [
        { sourcePath: 'DocNo', transform: 'string', sorentoField: 'so_number', scope: 'header' },
        ...lineRows.map((r) => ({
          sourcePath: r.sourcePath,
          transform: r.transform,
          sorentoField: r.sorentoField as string,
          formula: r.formula,
          scope: 'line' as const,
        })),
      ],
    });
    expect(saved.rows.filter((r) => r.scope === 'header')).toHaveLength(1);
    expect(saved.rows.filter((r) => r.scope === 'line')).toHaveLength(lineRows.length);
  });

  it('rejects a line row targeting an unaccepted field (AC-02-03)', async () => {
    await expect(
      service.updateMapping('company-1', 'sales_order', {
        rows: [
          { sourcePath: 'DocNo', transform: 'string', sorentoField: 'so_number', scope: 'header' },
          { sourcePath: 'DtlKey', transform: 'string', sorentoField: 'source_ref', scope: 'line' },
          { sourcePath: 'ItemAutoKey', transform: 'ref_product', sorentoField: 'product_ref', scope: 'line' },
          { sourcePath: 'Qty', transform: 'decimal', sorentoField: 'qty_ordered', scope: 'line' },
          { sourcePath: 'Bogus', transform: 'string', sorentoField: 'not_a_real_field', scope: 'line' },
        ],
      }),
    ).rejects.toMatchObject({ status: 422 });
  });

  it('rejects product_ref/warehouse_ref without their locked ref transform (AC-02-03)', async () => {
    await expect(
      service.updateMapping('company-1', 'sales_order', {
        rows: [
          { sourcePath: 'DocNo', transform: 'string', sorentoField: 'so_number', scope: 'header' },
          { sourcePath: 'DtlKey', transform: 'string', sorentoField: 'source_ref', scope: 'line' },
          { sourcePath: 'ItemAutoKey', transform: 'string', sorentoField: 'product_ref', scope: 'line' },
          { sourcePath: 'Qty', transform: 'decimal', sorentoField: 'qty_ordered', scope: 'line' },
        ],
      }),
    ).rejects.toMatchObject({ status: 422 });
  });

  it('rejects a line save missing source_ref/product_ref/qty_ordered (AC-02-03)', async () => {
    await expect(
      service.updateMapping('company-1', 'sales_order', {
        rows: [
          { sourcePath: 'DocNo', transform: 'string', sorentoField: 'so_number', scope: 'header' },
          { sourcePath: 'DtlKey', transform: 'string', sorentoField: 'source_ref', scope: 'line' },
        ],
      }),
    ).rejects.toMatchObject({ status: 422 });
  });

  it('lists the SO/PO/SPO presets with {database} substituted (AC-02-16/17)', async () => {
    const so = await service.listMappingPresets('company-1', 'sales_order');
    expect(so).toHaveLength(1);
    expect(so[0].headerQuery).not.toContain('{database}');
    expect(so[0].headerQuery).toContain('AED_VSOFT');
    expect(so[0].lineQuery).toContain(':doc_key');

    const po = await service.listMappingPresets('company-1', 'purchase_order');
    expect(po[0].filterFormula).toBe('not(startswith(upper(trim(DocNo)), "SPO-"))');

    const spo = await service.listMappingPresets('company-1', 'shipping_order');
    expect(spo[0].filterFormula).toBe('startswith(upper(trim(DocNo)), "SPO-")');
  });

  it('no preset for a master entity - never a dead picker (foolproof-UI)', async () => {
    expect(await service.listMappingPresets('company-1', 'customer')).toEqual([]);
  });

  it('simulate computes line aggregates + the default status formula (AC-02-07/08/22)', async () => {
    const view = await service.getMapping('company-1', 'sales_order');
    const header = { DocNo: 'SO-1001', Cancelled: 'F' };
    const lines = [
      { DtlKey: 'L1', ItemAutoKey: 'IK1', Qty: 10, TransferedQty: 10 }, // fulfilled
      { DtlKey: 'L2', ItemAutoKey: 'IK2', Qty: 5, TransferedQty: 0 }, // open
    ];
    const result = await service.simulateMapping(
      'company-1',
      'sales_order',
      header,
      view.rows
        .filter((r) => r.sorentoField)
        .map((r) => ({
          sourcePath: r.sourcePath,
          transform: r.transform,
          sorentoField: r.sorentoField as string,
          formula: r.formula,
          scope: r.scope as 'header' | 'line',
        })),
      lines,
    );
    expect(result.ok).toBe(true);
    expect(result.status).toBe('open');
    expect(result.lineFields).toHaveLength(2);
  });

  it('simulate reports "closed" once every line is fulfilled', async () => {
    const view = await service.getMapping('company-1', 'sales_order');
    const result = await service.simulateMapping(
      'company-1',
      'sales_order',
      { DocNo: 'SO-1002', Cancelled: 'F' },
      view.rows
        .filter((r) => r.sorentoField)
        .map((r) => ({
          sourcePath: r.sourcePath,
          transform: r.transform,
          sorentoField: r.sorentoField as string,
          formula: r.formula,
          scope: r.scope as 'header' | 'line',
        })),
      [{ DtlKey: 'L1', ItemAutoKey: 'IK1', Qty: 10, TransferedQty: 10 }],
    );
    expect(result.status).toBe('closed');
  });

  it('simulate reports "cancelled" regardless of open lines when Cancelled = T', async () => {
    const view = await service.getMapping('company-1', 'sales_order');
    const result = await service.simulateMapping(
      'company-1',
      'sales_order',
      { DocNo: 'SO-1003', Cancelled: 'T' },
      view.rows
        .filter((r) => r.sorentoField)
        .map((r) => ({
          sourcePath: r.sourcePath,
          transform: r.transform,
          sorentoField: r.sorentoField as string,
          formula: r.formula,
          scope: r.scope as 'header' | 'line',
        })),
      [{ DtlKey: 'L1', ItemAutoKey: 'IK1', Qty: 10, TransferedQty: 0 }],
    );
    expect(result.status).toBe('cancelled');
  });

  it('never emits partial by default (AC-02-15)', async () => {
    const view = await service.getMapping('company-1', 'purchase_order');
    for (const cancelled of ['T', 'F']) {
      for (const received of [0, 5, 10]) {
        const result = await service.simulateMapping(
          'company-1',
          'purchase_order',
          { DocNo: 'PO-1', UDF_Currency: null, CurrencyCode: null, Cancelled: cancelled },
          view.rows
            .filter((r) => r.sorentoField)
            .map((r) => ({
              sourcePath: r.sourcePath,
              transform: r.transform,
              sorentoField: r.sorentoField as string,
              formula: r.formula,
              scope: r.scope as 'header' | 'line',
            })),
          [{ DtlKey: 'L1', ItemAutoKey: 'IK1', Qty: 10, ReceivedQty: received }],
        );
        expect(result.status).not.toBe('partial');
      }
    }
  });

  it('master/GRN simulate is unchanged (lineFields empty, no lines arg)', async () => {
    const result = await service.simulateMapping('company-1', 'customer', {
      AccNo: 'A1',
      CompanyName: 'Acme',
      IsActive: 'T',
    });
    expect(result.lineFields).toEqual([]);
    expect(result.status ?? null).toBeNull();
  });
});

describe('mock document mapping - guard rejections carry ApiError (sanity)', () => {
  it('an unaccepted header target still 422s as before', async () => {
    let caught: unknown;
    try {
      await service.updateMapping('company-1', 'sales_order', {
        rows: [{ sourcePath: 'DocNo', transform: 'string', sorentoField: 'not_a_field' }],
      });
    } catch (e) {
      caught = e;
    }
    expect(caught).toBeInstanceOf(ApiError);
    expect((caught as ApiError).status).toBe(422);
  });
});
