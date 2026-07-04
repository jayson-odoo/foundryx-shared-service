/**
 * Finance service (sprint-4/05; Cluster F slice 1) — invoices, real `apiFetch` to
 * the finance module. Status rides the invoice status engine; transitions go
 * through the graph. Cluster F adds manual payments, freeze-aware update, and the
 * invoice/receipt PDF (fetched as an authed blob — an <a href> can't carry the
 * Bearer).
 */
import { apiFetch, apiFetchBlob } from '@/lib/api-client';
import type { ListQuery, ListResult } from '@/types/resource';
import type {
  Invoice,
  PaymentMethod,
  Refund,
  RefundableTicket,
  Settlement,
} from '@/types/registration';

interface EmsList<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
}

export interface RecordPaymentInput {
  amount: number;
  method: PaymentMethod;
  note?: string;
}

export interface InvoiceUpdateInput {
  notes?: string;
  buyerTin?: string;
  sstRegNo?: string;
  taxCode?: string;
  einvoiceType?: string;
}

/** Gateway checkout session (AC-07-27) — buyer redirect + the Pending payment id. */
export interface CheckoutResult {
  redirectUrl: string;
  paymentId: string;
}

export const financeService = {
  async listInvoicesQuery(q: ListQuery, projectId?: string): Promise<ListResult<Invoice>> {
    const sp = new URLSearchParams();
    sp.set('page', String(q.page));
    sp.set('page_size', String(q.pageSize));
    if (q.search) sp.set('search', q.search);
    if (projectId) sp.set('project_id', projectId);
    const p = await apiFetch<EmsList<Invoice>>(`/finance/invoices?${sp.toString()}`);
    return { data: p.items, total: p.total, page: p.page };
  },
  getInvoice(id: string): Promise<Invoice> {
    return apiFetch<Invoice>(`/finance/invoices/${id}`);
  },
  transitionInvoice(id: string, toStatusId: string): Promise<Invoice> {
    return apiFetch<Invoice>(`/finance/invoices/${id}/transition`, {
      method: 'POST',
      body: JSON.stringify({ toStatusId }),
    });
  },
  updateInvoice(id: string, body: InvoiceUpdateInput): Promise<Invoice> {
    return apiFetch<Invoice>(`/finance/invoices/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    });
  },
  recordPayment(id: string, body: RecordPaymentInput): Promise<Invoice> {
    return apiFetch<Invoice>(`/finance/invoices/${id}/payments`, {
      method: 'POST',
      body: JSON.stringify(body),
    });
  },
  /** Open a gateway checkout (AC-07-27): the backend creates a Pending payment
   * and returns the buyer redirect URL for the gateway hosted page. */
  startCheckout(id: string): Promise<CheckoutResult> {
    return apiFetch<CheckoutResult>(`/finance/invoices/${id}/checkout`, { method: 'POST' });
  },
  invoicePdf(id: string): Promise<Blob> {
    return apiFetchBlob(`/finance/invoices/${id}/pdf`);
  },
  // ── refunds (Cluster F slice 4, AC-07-37..43) ──────────────────────────────
  /** The invoice's tickets + a refundable flag — the refund picker source. */
  refundableTickets(invoiceId: string): Promise<RefundableTicket[]> {
    return apiFetch<RefundableTicket[]>(`/finance/invoices/${invoiceId}/refundable-tickets`);
  },
  listRefunds(invoiceId: string): Promise<Refund[]> {
    return apiFetch<Refund[]>(`/finance/invoices/${invoiceId}/refunds`);
  },
  /** Refund selected tickets (gateway or manual; over-refund guarded server-side). */
  createRefund(invoiceId: string, ticketIds: string[], reason?: string): Promise<Refund> {
    return apiFetch<Refund>(`/finance/invoices/${invoiceId}/refunds`, {
      method: 'POST',
      body: JSON.stringify({ ticketIds, reason }),
    });
  },
  /** Credit-note PDF for a confirmed refund (AC-07-40) — authed blob. */
  creditNotePdf(refundId: string): Promise<Blob> {
    return apiFetchBlob(`/finance/invoices/refunds/${refundId}/credit-note`);
  },
  // ── settlements (Cluster F slice 4, AC-07-45..48) ──────────────────────────
  async listSettlementsQuery(q: ListQuery, projectId?: string): Promise<ListResult<Settlement>> {
    const sp = new URLSearchParams();
    sp.set('page', String(q.page));
    sp.set('page_size', String(q.pageSize));
    if (projectId) sp.set('project_id', projectId);
    const p = await apiFetch<{ items: Settlement[]; total: number; page: number }>(
      `/finance/settlements?${sp.toString()}`,
    );
    return { data: p.items, total: p.total, page: p.page };
  },
  listSettlements(projectId?: string): Promise<Settlement[]> {
    const sp = new URLSearchParams({ page: '0', page_size: '100' });
    if (projectId) sp.set('project_id', projectId);
    return apiFetch<{ items: Settlement[] }>(`/finance/settlements?${sp.toString()}`).then(
      (p) => p.items,
    );
  },
  getSettlement(id: string): Promise<Settlement> {
    return apiFetch<Settlement>(`/finance/settlements/${id}`);
  },
  /** Generate a PRIMARY settlement for an AGENCY project (AC-07-46). */
  generateSettlement(projectId: string): Promise<Settlement> {
    return apiFetch<Settlement>('/finance/settlements', {
      method: 'POST',
      body: JSON.stringify({ projectId }),
    });
  },
  transitionSettlement(
    id: string,
    toStatusId: string,
    remittanceRef?: string,
  ): Promise<Settlement> {
    return apiFetch<Settlement>(`/finance/settlements/${id}/transition`, {
      method: 'POST',
      body: JSON.stringify({ toStatusId, remittanceRef }),
    });
  },
};
