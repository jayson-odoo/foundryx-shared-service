import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiFetch = vi.fn();
const apiFetchText = vi.fn();
vi.mock('@/lib/api-client', () => ({
  apiFetch: (...a: unknown[]) => apiFetch(...a),
  apiFetchText: (...a: unknown[]) => apiFetchText(...a),
}));

import { emsService } from './ems-service';

beforeEach(() => {
  vi.clearAllMocks();
});

describe('emsService sales orders (Cluster F slice 2)', () => {
  it('listSalesOrdersQuery maps the EMS page → ListResult', async () => {
    apiFetch.mockResolvedValue({ items: [{ id: 'so1' }], total: 1, page: 0, pageSize: 25 });
    const res = await emsService.listSalesOrdersQuery({ page: 0, pageSize: 25, statusView: 'active' });
    expect(apiFetch.mock.calls[0][0]).toContain('/crm/sales-orders?');
    expect(res).toMatchObject({ data: [{ id: 'so1' }], total: 1, page: 0 });
  });

  it('createSalesOrderFromQuotation POSTs the from-quotation endpoint', async () => {
    apiFetch.mockResolvedValue({ id: 'so2' });
    await emsService.createSalesOrderFromQuotation('q1');
    const [path, opts] = apiFetch.mock.calls[0];
    expect(path).toBe('/crm/sales-orders/from-quotation');
    expect(opts).toMatchObject({ method: 'POST' });
    expect(JSON.parse((opts as { body: string }).body)).toEqual({ quotationId: 'q1' });
  });

  it('transitionSalesOrder POSTs the target status', async () => {
    apiFetch.mockResolvedValue({ id: 'so1', statusId: 's2' });
    await emsService.transitionSalesOrder('so1', 's2');
    const [path, opts] = apiFetch.mock.calls[0];
    expect(path).toBe('/crm/sales-orders/so1/transition');
    expect(JSON.parse((opts as { body: string }).body)).toEqual({ toStatusId: 's2' });
  });

  it('createInvoiceFromSalesOrder POSTs the selections', async () => {
    apiFetch.mockResolvedValue({ id: 'inv1', total: 100, currency: 'USD' });
    const res = await emsService.createInvoiceFromSalesOrder('so1', [{ lineId: 'l1', qty: 3 }]);
    const [path, opts] = apiFetch.mock.calls[0];
    expect(path).toBe('/crm/sales-orders/so1/create-invoice');
    expect(JSON.parse((opts as { body: string }).body)).toEqual({ selections: [{ lineId: 'l1', qty: 3 }] });
    expect(res).toMatchObject({ id: 'inv1', total: 100 });
  });

  it('exportSalesOrders POSTs the export with trashed flag', async () => {
    apiFetchText.mockResolvedValue('id\nso1\n');
    await emsService.exportSalesOrders({ page: 0, pageSize: 25, statusView: 'trashed', search: 'x' }, ['id'], ['so1']);
    const [path, opts] = apiFetchText.mock.calls[0];
    expect(path).toBe('/crm/sales-orders/export');
    expect(JSON.parse((opts as { body: string }).body)).toMatchObject({ columns: ['id'], ids: ['so1'], search: 'x', trashed: true });
  });
});
