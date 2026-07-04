import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiFetch = vi.fn();
const apiFetchBlob = vi.fn();
vi.mock('@/lib/api-client', () => ({
  apiFetch: (...a: unknown[]) => apiFetch(...a),
  apiFetchBlob: (...a: unknown[]) => apiFetchBlob(...a),
}));

import { financeService } from './finance-service';

beforeEach(() => {
  vi.clearAllMocks();
});

describe('financeService (sprint-4/07 Cluster F slice 1)', () => {
  it('recordPayment POSTs the payments endpoint with method + amount', async () => {
    apiFetch.mockResolvedValue({ id: 'inv1', statusKey: 'partially_paid', paidTotal: 40 });
    const res = await financeService.recordPayment('inv1', { amount: 40, method: 'CASH', note: 'x' });
    const [path, opts] = apiFetch.mock.calls[0];
    expect(path).toBe('/finance/invoices/inv1/payments');
    expect(opts).toMatchObject({ method: 'POST' });
    expect(JSON.parse((opts as { body: string }).body)).toMatchObject({ amount: 40, method: 'CASH', note: 'x' });
    expect(res).toMatchObject({ statusKey: 'partially_paid' });
  });

  it('updateInvoice PATCHes the invoice', async () => {
    apiFetch.mockResolvedValue({ id: 'inv1', notes: 'hi' });
    await financeService.updateInvoice('inv1', { notes: 'hi' });
    const [path, opts] = apiFetch.mock.calls[0];
    expect(path).toBe('/finance/invoices/inv1');
    expect(opts).toMatchObject({ method: 'PATCH' });
    expect(JSON.parse((opts as { body: string }).body)).toMatchObject({ notes: 'hi' });
  });

  it('transitionInvoice POSTs the transition endpoint', async () => {
    apiFetch.mockResolvedValue({ id: 'inv1', statusKey: 'void' });
    await financeService.transitionInvoice('inv1', 'st-void');
    const [path, opts] = apiFetch.mock.calls[0];
    expect(path).toBe('/finance/invoices/inv1/transition');
    expect(JSON.parse((opts as { body: string }).body)).toMatchObject({ toStatusId: 'st-void' });
  });

  it('invoicePdf fetches the pdf endpoint as a blob', async () => {
    const blob = new Blob(['%PDF'], { type: 'application/pdf' });
    apiFetchBlob.mockResolvedValue(blob);
    const res = await financeService.invoicePdf('inv1');
    expect(apiFetchBlob.mock.calls[0][0]).toBe('/finance/invoices/inv1/pdf');
    expect(res).toBe(blob);
  });

  it('startCheckout POSTs the checkout endpoint and returns the redirect URL (AC-07-27)', async () => {
    apiFetch.mockResolvedValue({ redirectUrl: 'https://stripe.test/cs_1', paymentId: 'pay1' });
    const res = await financeService.startCheckout('inv1');
    const [path, opts] = apiFetch.mock.calls[0];
    expect(path).toBe('/finance/invoices/inv1/checkout');
    expect(opts).toMatchObject({ method: 'POST' });
    expect(res).toMatchObject({ redirectUrl: 'https://stripe.test/cs_1', paymentId: 'pay1' });
  });
});

describe('financeService refunds + settlements (sprint-4/07 Cluster F slice 4)', () => {
  it('refundableTickets GETs the invoice refundable-tickets endpoint (AC-07-37)', async () => {
    apiFetch.mockResolvedValue([{ id: 't1', status: 'valid', refundable: true }]);
    const res = await financeService.refundableTickets('inv1');
    expect(apiFetch.mock.calls[0][0]).toBe('/finance/invoices/inv1/refundable-tickets');
    expect(res).toHaveLength(1);
  });

  it('createRefund POSTs the selected ticket ids + reason (AC-07-37/39)', async () => {
    apiFetch.mockResolvedValue({ id: 'r1', method: 'CASH', statusKey: 'confirmed', creditNoteNumber: 'CN-2026-1' });
    const res = await financeService.createRefund('inv1', ['t1', 't2'], 'changed mind');
    const [path, opts] = apiFetch.mock.calls[0];
    expect(path).toBe('/finance/invoices/inv1/refunds');
    expect(opts).toMatchObject({ method: 'POST' });
    expect(JSON.parse((opts as { body: string }).body)).toMatchObject({
      ticketIds: ['t1', 't2'],
      reason: 'changed mind',
    });
    expect(res).toMatchObject({ creditNoteNumber: 'CN-2026-1' });
  });

  it('creditNotePdf fetches the credit-note endpoint as a blob (AC-07-40)', async () => {
    const blob = new Blob(['%PDF'], { type: 'application/pdf' });
    apiFetchBlob.mockResolvedValue(blob);
    const res = await financeService.creditNotePdf('r1');
    expect(apiFetchBlob.mock.calls[0][0]).toBe('/finance/invoices/refunds/r1/credit-note');
    expect(res).toBe(blob);
  });

  it('generateSettlement POSTs the project id (AC-07-46)', async () => {
    apiFetch.mockResolvedValue({ id: 's1', kind: 'PRIMARY', netPayable: 90 });
    const res = await financeService.generateSettlement('proj1');
    const [path, opts] = apiFetch.mock.calls[0];
    expect(path).toBe('/finance/settlements');
    expect(JSON.parse((opts as { body: string }).body)).toMatchObject({ projectId: 'proj1' });
    expect(res).toMatchObject({ netPayable: 90 });
  });

  it('transitionSettlement POSTs the target status + remittance ref (AC-07-47)', async () => {
    apiFetch.mockResolvedValue({ id: 's1', statusKey: 'remitted', remittanceRef: 'TXN-1' });
    await financeService.transitionSettlement('s1', 'st-remitted', 'TXN-1');
    const [path, opts] = apiFetch.mock.calls[0];
    expect(path).toBe('/finance/settlements/s1/transition');
    expect(JSON.parse((opts as { body: string }).body)).toMatchObject({
      toStatusId: 'st-remitted',
      remittanceRef: 'TXN-1',
    });
  });

  it('listSettlements filters by project id', async () => {
    apiFetch.mockResolvedValue({ items: [{ id: 's1' }], total: 1, page: 0 });
    const res = await financeService.listSettlements('proj1');
    expect(apiFetch.mock.calls[0][0]).toContain('project_id=proj1');
    expect(res).toHaveLength(1);
  });
});
