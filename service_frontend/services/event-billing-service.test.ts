import { beforeEach, describe, expect, it, vi } from 'vitest';

const apiFetch = vi.fn();
vi.mock('@/lib/api-client', () => ({
  apiFetch: (...a: unknown[]) => apiFetch(...a),
}));

import { eventBillingService } from './event-billing-service';

beforeEach(() => {
  vi.clearAllMocks();
});

describe('eventBillingService.listRegistrations', () => {
  it('calls the event-wide tickets endpoint and maps rows to EventRegistration', async () => {
    apiFetch.mockResolvedValue({
      items: [
        {
          id: 'tk1',
          attendeeName: 'Ann Lee',
          attendeeEmail: 'ann@x.com',
          offeringName: 'VIP Pass',
          seatLabel: 'A1',
          ticketStatus: 'Issued',
          ticketStatusKey: 'issued',
          paid: false,
          invoiceId: 'inv1',
          invoiceTotal: 55,
          currency: 'MYR',
          qrToken: 'gAAAA-signed-token',
          registeredAt: '2026-06-21T00:00:00Z',
        },
      ],
      total: 1,
      page: 0,
      pageSize: 200,
    });

    const rows = await eventBillingService.listRegistrations('p1');
    const [path] = apiFetch.mock.calls[0];
    expect(path).toBe('/ems/projects/p1/tickets?page=0&page_size=200');
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({
      id: 'tk1',
      attendeeName: 'Ann Lee',
      offeringName: 'VIP Pass',
      seatLabel: 'A1',
      ticketStatus: 'Issued',
      ticketStatusKey: 'issued',
      paid: false,
      invoiceId: 'inv1',
      invoiceTotal: 55,
      currency: 'MYR',
      qrToken: 'gAAAA-signed-token', // AC-05-TKT-02: QR carried to the admin tab
    });
  });

  it('passes through null invoice fields for a comp ticket', async () => {
    apiFetch.mockResolvedValue({
      items: [
        {
          id: 'tk2',
          attendeeName: 'Vee',
          attendeeEmail: 'vee@x.com',
          offeringName: 'Comp',
          seatLabel: null,
          ticketStatus: 'Issued',
          ticketStatusKey: 'issued',
          paid: true,
          invoiceId: null,
          invoiceTotal: null,
          currency: null,
          registeredAt: '2026-06-21T00:00:00Z',
        },
      ],
      total: 1,
      page: 0,
      pageSize: 200,
    });
    const rows = await eventBillingService.listRegistrations('p1');
    expect(rows[0].invoiceId).toBeNull();
    expect(rows[0].invoiceTotal).toBeNull();
    expect(rows[0].currency).toBeNull();
    expect(rows[0].paid).toBe(true);
  });
});

describe('eventBillingService.adminRegister', () => {
  it('POSTs the add-one body to /register and returns the result', async () => {
    apiFetch.mockResolvedValue({
      orderRef: 'REG-ABC123',
      invoiceId: 'inv9',
      total: 55,
      currency: 'MYR',
      ticketCount: 1,
      confirmationEmails: ['ann@x.com'],
    });

    const res = await eventBillingService.adminRegister('p1', {
      items: [
        {
          offeringId: 'off1',
          attendee: { name: 'Ann Lee', email: 'ann@x.com', phone: '+60123' },
          capacityUnitId: 'seat-A1',
        },
      ],
      comp: false,
    });

    const [path, opts] = apiFetch.mock.calls[0];
    expect(path).toBe('/ems/projects/p1/register');
    expect(opts).toMatchObject({ method: 'POST' });
    expect(JSON.parse(opts.body)).toEqual({
      items: [
        {
          offeringId: 'off1',
          attendee: { name: 'Ann Lee', email: 'ann@x.com', phone: '+60123' },
          capacityUnitId: 'seat-A1',
        },
      ],
      comp: false,
    });
    expect(res.orderRef).toBe('REG-ABC123');
    expect(res.ticketCount).toBe(1);
  });

  it('sends a comp registration without an invoice expectation', async () => {
    apiFetch.mockResolvedValue({
      orderRef: 'REG-ZZZ000',
      invoiceId: null,
      total: null,
      currency: null,
      ticketCount: 1,
      confirmationEmails: ['vee@x.com'],
    });
    const res = await eventBillingService.adminRegister('p1', {
      items: [{ offeringId: 'gaOff', attendee: { email: 'vee@x.com' } }],
      comp: true,
    });
    const [, opts] = apiFetch.mock.calls[0];
    expect(JSON.parse(opts.body).comp).toBe(true);
    expect(JSON.parse(opts.body).items[0].capacityUnitId).toBeUndefined();
    expect(res.invoiceId).toBeNull();
  });
});

describe('eventBillingService invoices (real finance)', () => {
  it('listInvoices maps finance invoices to EventInvoice', async () => {
    apiFetch.mockResolvedValue({
      items: [
        {
          id: 'inv1',
          projectId: 'p1',
          billToType: 'Profile',
          billToId: 'prof-123456789',
          currency: 'MYR',
          statusId: 's1',
          statusLabel: 'Issued',
          billToName: 'Ann Lee',
          subtotal: 50,
          tax: 5,
          total: 55,
          createdAt: '2026-06-21T00:00:00Z',
          lines: [{ id: 'l1', description: 'VIP', qty: 1, unitPrice: 50, tax: 5, amount: 50 }],
        },
      ],
      total: 1,
      page: 0,
      pageSize: 200,
    });
    const rows = await eventBillingService.listInvoices('p1');
    const [path] = apiFetch.mock.calls[0];
    expect(path).toBe('/finance/invoices?project_id=p1&page=0&page_size=200');
    expect(rows[0]).toMatchObject({
      id: 'inv1',
      billToName: 'Ann Lee',
      billToType: 'Profile',
      total: 55,
      currency: 'MYR',
      status: 'Issued',
      lineCount: 1,
    });
  });

  it('getInvoice maps a finance invoice to EventInvoiceDetail with lines', async () => {
    apiFetch.mockResolvedValue({
      id: 'inv1',
      projectId: 'p1',
      billToType: 'Profile',
      billToId: 'prof-1',
      currency: 'MYR',
      statusId: 's1',
      statusLabel: 'Paid',
      billToName: 'Ann Lee',
      subtotal: 50,
      tax: 5,
      total: 55,
      createdAt: '2026-06-21T00:00:00Z',
      lines: [{ id: 'l1', description: 'VIP', qty: 1, unitPrice: 50, tax: 5, amount: 50 }],
    });
    const inv = await eventBillingService.getInvoice('p1', 'inv1');
    const [path] = apiFetch.mock.calls[0];
    expect(path).toBe('/finance/invoices/inv1');
    expect(inv.status).toBe('Paid');
    expect(inv.subtotal).toBe(50);
    expect(inv.lines).toHaveLength(1);
    expect(inv.lines[0]).toMatchObject({ description: 'VIP', qty: 1, unitPrice: 50, amount: 50 });
  });

  it('coerces an unknown status label to Draft', async () => {
    apiFetch.mockResolvedValue({
      items: [
        {
          id: 'inv2', projectId: 'p1', billToType: 'Client', billToId: 'c1', currency: 'USD',
          statusId: null, statusLabel: 'Weird', billToName: '', subtotal: 0, tax: 0, total: 0,
          createdAt: '2026-06-21T00:00:00Z', lines: [],
        },
      ],
      total: 1, page: 0, pageSize: 200,
    });
    const rows = await eventBillingService.listInvoices('p1');
    expect(rows[0].status).toBe('Draft');
    expect(rows[0].billToName).toBe('c1'); // falls back to billToId slice
  });
});
