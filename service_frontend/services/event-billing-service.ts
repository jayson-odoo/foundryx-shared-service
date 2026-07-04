/**
 * Event registrations + invoices (admin) and the portal order view — Cluster D
 * (sprint-4/05), BL-120 backend wiring.
 *
 * REAL-BOUND (since BL-120): `listRegistrations` → `GET /ems/projects/{id}/tickets`
 * (the event-wide tickets list), `listInvoices`/`getInvoice` → the finance module
 * (`GET /finance/invoices?project_id=` / `/{id}`). The `eventBillingService`
 * boundary + method signatures are unchanged so consumers don't move.
 *
 * STILL MOCK: `getPortalOrder` — no real portal order endpoint exists yet
 * (TODO(BL-120) below).
 */
import { apiFetch } from '@/lib/api-client';
import type {
  AdminRegisterRequest,
  AdminRegisterResult,
  EventInvoice,
  EventInvoiceDetail,
  EventRegistration,
  Invoice,
  PortalOrder,
} from '@/types/registration';

interface EmsList<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
}

/** Backend row from `GET /ems/projects/{id}/tickets` (TicketRowOut). */
interface TicketRow {
  id: string;
  attendeeName: string;
  attendeeEmail: string;
  offeringName: string;
  seatLabel: string | null;
  ticketStatus: string;
  ticketStatusKey: string;
  paid: boolean;
  invoiceId: string | null;
  invoiceTotal: number | null;
  currency: string | null;
  qrToken: string | null;
  registeredAt: string;
}

function toRegistration(t: TicketRow): EventRegistration {
  return {
    id: t.id,
    attendeeName: t.attendeeName,
    attendeeEmail: t.attendeeEmail,
    offeringName: t.offeringName,
    seatLabel: t.seatLabel,
    ticketStatus: t.ticketStatus,
    ticketStatusKey: t.ticketStatusKey,
    paid: t.paid,
    invoiceId: t.invoiceId,
    invoiceTotal: t.invoiceTotal,
    currency: t.currency,
    qrToken: t.qrToken ?? null,
    registeredAt: t.registeredAt,
  };
}

const KNOWN_STATUSES: EventInvoice['status'][] = ['Draft', 'Issued', 'Paid', 'Cancelled'];
function toInvoiceStatus(label: string | null): EventInvoice['status'] {
  return KNOWN_STATUSES.find((s) => s === label) ?? 'Draft';
}
function toBillToType(t: string): EventInvoice['billToType'] {
  return t === 'Client' ? 'Client' : 'Profile';
}

function toEventInvoice(inv: Invoice): EventInvoice {
  return {
    id: inv.id,
    billToName: inv.billToName || inv.billToId.slice(0, 8),
    billToType: toBillToType(inv.billToType),
    total: inv.total,
    currency: inv.currency,
    status: toInvoiceStatus(inv.statusLabel),
    lineCount: inv.lines.length,
    createdAt: inv.createdAt,
  };
}

function toEventInvoiceDetail(inv: Invoice): EventInvoiceDetail {
  return {
    id: inv.id,
    billToName: inv.billToName || inv.billToId.slice(0, 8),
    billToType: toBillToType(inv.billToType),
    status: toInvoiceStatus(inv.statusLabel),
    currency: inv.currency,
    subtotal: inv.subtotal,
    tax: inv.tax,
    total: inv.total,
    createdAt: inv.createdAt,
    lines: inv.lines.map((l) => ({
      id: l.id,
      description: l.description ?? '',
      qty: l.qty,
      unitPrice: l.unitPrice,
      tax: l.tax,
      amount: l.amount,
    })),
  };
}

export const eventBillingService = {
  async listRegistrations(projectId: string): Promise<EventRegistration[]> {
    const p = await apiFetch<EmsList<TicketRow>>(
      `/ems/projects/${projectId}/tickets?page=0&page_size=200`,
    );
    return p.items.map(toRegistration);
  },

  /** Admin add-one (AC-05-CART-09) — `POST /ems/projects/{id}/register`. Mints a
   * participant + signed-QR ticket per item + ONE Draft invoice (skipped when
   * `comp`). Atomic; surfaces the backend 422/409 message on failure. */
  async adminRegister(
    projectId: string,
    body: AdminRegisterRequest,
  ): Promise<AdminRegisterResult> {
    return apiFetch<AdminRegisterResult>(`/ems/projects/${projectId}/register`, {
      method: 'POST',
      body: JSON.stringify(body),
    });
  },

  async listInvoices(projectId: string): Promise<EventInvoice[]> {
    const p = await apiFetch<EmsList<Invoice>>(
      `/finance/invoices?project_id=${projectId}&page=0&page_size=200`,
    );
    return p.items.map(toEventInvoice);
  },

  async getInvoice(_projectId: string, invoiceId: string): Promise<EventInvoiceDetail> {
    const inv = await apiFetch<Invoice>(`/finance/invoices/${invoiceId}`);
    return toEventInvoiceDetail(inv);
  },

  /** Portal — a participant's order. TODO(BL-120): no real portal order endpoint
   * exists yet, so this stays an in-memory mock. The backend resolves it from the
   * order ref / confirmation token once the portal order surface lands. */
  async getPortalOrder(orderRef: string, eventTitle: string, paid: boolean): Promise<PortalOrder> {
    return {
      orderRef,
      eventTitle: eventTitle || 'Your event',
      invoiceTotal: 215.82,
      currency: 'MYR',
      paid,
      tickets: [
        { id: 't1', offeringName: 'General Admission', seatLabel: null, attendeeName: 'You', status: paid ? 'valid' : 'issued' },
        { id: 't2', offeringName: 'VIP Reserved Seat', seatLabel: 'A2', attendeeName: 'You', status: paid ? 'valid' : 'issued' },
      ],
    };
  },
};
