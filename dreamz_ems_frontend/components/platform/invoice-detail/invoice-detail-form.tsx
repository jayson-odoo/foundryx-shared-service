'use client';

/** Invoice detail as an EMBEDDED ResourceForm (sprint-4/05) — form-in-form. Same
 * chrome as a page form: top-right Back + record-nav + "…" actions, FormRow
 * fields, line-item table. Status from the invoice status engine; the outgoing
 * graph edges become "…" actions labelled with the bare target status (Issue /
 * Cancel / … — Paid etc. arrive with Cluster F). Reusable in event invoices, the
 * global Invoices list, and (later) a participant's invoices. */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import {
  ArrowRight,
  CreditCard,
  Download,
  LoaderCircleIcon,
  Receipt,
  RotateCcw,
  Wallet,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { ResourceForm } from '@/components/platform/resource-form';
import { FormRow } from '@/components/platform/resource-form/form-row';
import type { ResourceFormConfig } from '@/components/platform/resource-form/types';
import type { ResourceAction } from '@/components/platform/resource-list';
import type { DetailNav } from '@/components/platform/resource-master-detail';
import { useStatusGraph } from '@/hooks/use-status-engine';
import { useDatetime } from '@/hooks/use-datetime';
import { financeService } from '@/services/finance-service';
import { formatMoney } from '@/lib/money';
import { invoiceStatusVariant } from '@/lib/invoice-status';
import type { Invoice, Refund } from '@/types/registration';
import { RecordPaymentDialog } from './record-payment-dialog';
import { RefundDialog } from './refund-dialog';

/** Statuses that can still accept a manual payment (AC-07-10). */
const PAYABLE_KEYS = new Set(['issued', 'partially_paid', 'overdue']);
/** Statuses where refunding tickets is offered (paid money exists). */
const REFUNDABLE_KEYS = new Set(['paid', 'partially_paid', 'partially_refunded', 'overdue']);

export function InvoiceDetailForm({
  invoiceId,
  nav,
  backLabel = 'Back to invoices',
}: {
  invoiceId: string;
  nav: DetailNav;
  backLabel?: string;
}) {
  const [inv, setInv] = useState<Invoice | null>(null);
  const [loading, setLoading] = useState(true);
  const [payOpen, setPayOpen] = useState(false);
  const [refundOpen, setRefundOpen] = useState(false);
  const [refunds, setRefunds] = useState<Refund[]>([]);
  const engine = useStatusGraph('invoice');
  const { formatDate, formatDateTime } = useDatetime();

  const load = useCallback(() => {
    financeService.getInvoice(invoiceId).then(setInv).finally(() => setLoading(false));
    financeService.listRefunds(invoiceId).then(setRefunds).catch(() => setRefunds([]));
  }, [invoiceId]);
  useEffect(() => load(), [load]);

  async function downloadCreditNote(refundId: string) {
    try {
      const blob = await financeService.creditNotePdf(refundId);
      const url = URL.createObjectURL(blob);
      window.open(url, '_blank', 'noopener');
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not generate the credit note.');
    }
  }

  async function downloadPdf(invoice: Invoice) {
    try {
      const blob = await financeService.invoicePdf(invoice.id);
      const url = URL.createObjectURL(blob);
      window.open(url, '_blank', 'noopener');
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not generate the PDF.');
    }
  }

  const statusLabel = useMemo(
    () => new Map((engine.graph?.statuses ?? []).map((s) => [s.id, s.label])),
    [engine.graph],
  );

  const config = useMemo<ResourceFormConfig<Invoice> | null>(() => {
    if (!inv) return null;
    const label = inv.statusLabel ?? '—';
    const variant = invoiceStatusVariant(label);

    // graph-driven transitions → "…" actions (bare target-status labels)
    const actions: ResourceAction<Invoice>[] = (engine.graph?.transitions ?? [])
      .filter((t) => t.triggerMode !== 'auto' && t.fromStatusId === inv.statusId)
      .map((t) => ({
        id: `move-${t.toStatusId}`,
        label: statusLabel.get(t.toStatusId) || t.label,
        icon: ArrowRight,
        surfaces: { row: false, form: true, bulk: false },
        run: async () => {
          try {
            setInv(await financeService.transitionInvoice(inv.id, t.toStatusId));
          } catch (e) {
            toast.error(e instanceof Error ? e.message : 'Could not change the status.');
          }
        },
      }));

    // Record-payment (AC-07-10) — only while the invoice can accept payments.
    if (inv.statusKey && PAYABLE_KEYS.has(inv.statusKey)) {
      actions.push({
        id: 'record-payment',
        label: 'Record payment',
        icon: CreditCard,
        surfaces: { row: false, form: true, bulk: false },
        run: async () => setPayOpen(true),
      });
      // Pay online (AC-07-27) — opens a gateway checkout and redirects the buyer
      // to the hosted page. Only offered while there is an outstanding balance.
      if (inv.total - inv.paidTotal > 0) {
        actions.push({
          id: 'pay-online',
          label: 'Pay online',
          icon: Wallet,
          surfaces: { row: false, form: true, bulk: false },
          run: async () => {
            try {
              const { redirectUrl } = await financeService.startCheckout(inv.id);
              window.location.href = redirectUrl;
            } catch (e) {
              toast.error(e instanceof Error ? e.message : 'Could not start checkout.');
            }
          },
        });
      }
    }
    // Refund tickets (AC-07-37) — only when there's captured money to refund.
    if (inv.statusKey && REFUNDABLE_KEYS.has(inv.statusKey) && inv.paidTotal > 0) {
      actions.push({
        id: 'refund',
        label: 'Refund tickets',
        icon: RotateCcw,
        surfaces: { row: false, form: true, bulk: false },
        run: async () => setRefundOpen(true),
      });
    }
    // Download PDF / receipt (AC-07-17/18) — available once the invoice has a
    // number (i.e. issued; a Draft has nothing to print).
    if (inv.invoiceNumber) {
      actions.push({
        id: 'download-pdf',
        label: inv.statusKey === 'paid' ? 'Download receipt' : 'Download PDF',
        icon: Download,
        surfaces: { row: false, form: true, bulk: false },
        run: async () => downloadPdf(inv),
      });
    }

    return {
      breadcrumb: [],
      backHref: '#',
      backLabel,
      title: `Invoice · ${inv.billToName || inv.billToId.slice(0, 8)}`,
      subtitle: formatMoney(inv.total, inv.currency),
      tabs: [
        {
          id: 'invoice',
          label: 'Invoice',
          icon: Receipt,
          render: () => (
            <div className="max-w-3xl space-y-5">
              <div>
                <FormRow label="Bill to">
                  <span className="inline-flex items-center gap-2">
                    {inv.billToName || inv.billToId}
                    <Badge variant="secondary" appearance="light" size="sm">{inv.billToType}</Badge>
                  </span>
                </FormRow>
                <FormRow label="Status">
                  <Badge variant={variant} appearance="light" size="sm">{label}</Badge>
                </FormRow>
                <FormRow label="Invoice no.">
                  <span className="font-mono text-xs text-muted-foreground">
                    {inv.invoiceNumber || '— (draft)'}
                  </span>
                </FormRow>
                {inv.dueDate && (
                  <FormRow label="Due date">
                    <span className="text-sm">{formatDate(inv.dueDate)}</span>
                  </FormRow>
                )}
                {inv.buyerTin && (
                  <FormRow label="Buyer TIN">
                    <span className="text-sm">{inv.buyerTin}</span>
                  </FormRow>
                )}
              </div>

              <div className="overflow-x-auto rounded-lg border border-border">
                <table className="w-full text-sm">
                  <thead className="bg-muted/40 text-left text-xs text-muted-foreground">
                    <tr>
                      <th className="px-3 py-2 font-medium">Description</th>
                      <th className="px-3 py-2 text-right font-medium">Qty</th>
                      <th className="px-3 py-2 text-right font-medium">Unit</th>
                      <th className="px-3 py-2 text-right font-medium">Tax</th>
                      <th className="px-3 py-2 text-right font-medium">Amount</th>
                    </tr>
                  </thead>
                  <tbody>
                    {inv.lines.map((l) => (
                      <tr key={l.id} className="border-t border-border">
                        <td className="px-3 py-2">{l.description || '—'}</td>
                        <td className="px-3 py-2 text-right">{l.qty}</td>
                        <td className="px-3 py-2 text-right">{formatMoney(l.unitPrice, inv.currency)}</td>
                        <td className="px-3 py-2 text-right text-muted-foreground">{formatMoney(l.tax, inv.currency)}</td>
                        <td className="px-3 py-2 text-right">{formatMoney(l.amount, inv.currency)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="ms-auto w-full max-w-xs space-y-1 text-sm">
                <div className="flex justify-between text-muted-foreground"><span>Subtotal</span><span>{formatMoney(inv.subtotal, inv.currency)}</span></div>
                {inv.taxSummary.map((t) => (
                  <div key={t.label} className="flex justify-between text-muted-foreground">
                    <span>Tax ({t.label})</span><span>{formatMoney(t.tax, inv.currency)}</span>
                  </div>
                ))}
                <div className="flex justify-between border-t border-border pt-1 font-semibold"><span>Total</span><span>{formatMoney(inv.total, inv.currency)}</span></div>
                {inv.paidTotal > 0 && (
                  <>
                    <div className="flex justify-between text-muted-foreground"><span>Paid</span><span>{formatMoney(inv.paidTotal, inv.currency)}</span></div>
                    <div className="flex justify-between font-medium"><span>Balance</span><span>{formatMoney(inv.total - inv.paidTotal, inv.currency)}</span></div>
                  </>
                )}
              </div>
            </div>
          ),
        },
        {
          id: 'payments',
          label: 'Payments',
          icon: CreditCard,
          render: () => (
            <div className="max-w-3xl space-y-4">
              {inv.payments.length === 0 ? (
                <p className="py-8 text-center text-sm text-muted-foreground">No payments recorded.</p>
              ) : (
                <div className="overflow-x-auto rounded-lg border border-border">
                  <table className="w-full text-sm">
                    <thead className="bg-muted/40 text-left text-xs text-muted-foreground">
                      <tr>
                        <th className="px-3 py-2 font-medium">Date</th>
                        <th className="px-3 py-2 font-medium">Method</th>
                        <th className="px-3 py-2 font-medium">Note</th>
                        <th className="px-3 py-2 text-right font-medium">Amount</th>
                      </tr>
                    </thead>
                    <tbody>
                      {inv.payments.map((p) => (
                        <tr key={p.id} className="border-t border-border">
                          <td className="px-3 py-2">{p.paidAt ? formatDateTime(p.paidAt) : '—'}</td>
                          <td className="px-3 py-2">
                            <Badge variant="secondary" appearance="light" size="sm">{p.method}</Badge>
                          </td>
                          <td className="px-3 py-2 text-muted-foreground">{p.note || '—'}</td>
                          <td className="px-3 py-2 text-right font-medium">{formatMoney(p.amount, inv.currency)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <div className="ms-auto w-full max-w-xs space-y-1 text-sm">
                <div className="flex justify-between text-muted-foreground"><span>Total</span><span>{formatMoney(inv.total, inv.currency)}</span></div>
                <div className="flex justify-between text-muted-foreground"><span>Paid</span><span>{formatMoney(inv.paidTotal, inv.currency)}</span></div>
                <div className="flex justify-between border-t border-border pt-1 font-semibold"><span>Balance</span><span>{formatMoney(inv.total - inv.paidTotal, inv.currency)}</span></div>
              </div>
            </div>
          ),
        },
        {
          id: 'refunds',
          label: 'Refunds',
          icon: RotateCcw,
          render: () => (
            <div className="max-w-3xl space-y-4">
              {refunds.length === 0 ? (
                <p className="py-8 text-center text-sm text-muted-foreground">No refunds.</p>
              ) : (
                <div className="overflow-x-auto rounded-lg border border-border">
                  <table className="w-full text-sm">
                    <thead className="bg-muted/40 text-left text-xs text-muted-foreground">
                      <tr>
                        <th className="px-3 py-2 font-medium">Date</th>
                        <th className="px-3 py-2 font-medium">Method</th>
                        <th className="px-3 py-2 font-medium">Credit note</th>
                        <th className="px-3 py-2 font-medium">Reason</th>
                        <th className="px-3 py-2 text-right font-medium">Amount</th>
                        <th className="px-3 py-2 text-right font-medium" />
                      </tr>
                    </thead>
                    <tbody>
                      {refunds.map((r) => (
                        <tr key={r.id} className="border-t border-border">
                          <td className="px-3 py-2">{formatDateTime(r.createdAt)}</td>
                          <td className="px-3 py-2">
                            <Badge variant="secondary" appearance="light" size="sm">{r.method}</Badge>
                          </td>
                          <td className="px-3 py-2 font-mono text-xs">{r.creditNoteNumber || '—'}</td>
                          <td className="px-3 py-2 text-muted-foreground">{r.reason || '—'}</td>
                          <td className="px-3 py-2 text-right font-medium">{formatMoney(r.amount, inv.currency)}</td>
                          <td className="px-3 py-2 text-right">
                            {r.creditNoteNumber && (
                              <button
                                type="button"
                                className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
                                onClick={() => downloadCreditNote(r.id)}
                              >
                                <Download className="size-3.5" /> Credit note
                              </button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          ),
        },
      ],
      actions,
      actionRows: [inv],
      onReload: load,
      editable: false,
      isDirty: false,
      onSave: () => true,
      onCancel: () => {},
      embedded: true,
      onBack: nav.onBack,
      inlineNav: { index: nav.index, total: nav.total, onPrev: nav.onPrev, onNext: nav.onNext },
    };
  }, [inv, engine.graph, statusLabel, nav, backLabel, load, formatDate, formatDateTime, refunds]);

  if (loading || !config || !inv) {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground">
        <LoaderCircleIcon className="size-5 animate-spin" />
      </div>
    );
  }
  return (
    <>
      <ResourceForm config={config} />
      <RecordPaymentDialog
        invoice={inv}
        open={payOpen}
        onOpenChange={setPayOpen}
        onRecorded={(updated) => setInv(updated)}
      />
      <RefundDialog
        invoice={inv}
        open={refundOpen}
        onOpenChange={setRefundOpen}
        onRefunded={load}
      />
    </>
  );
}
