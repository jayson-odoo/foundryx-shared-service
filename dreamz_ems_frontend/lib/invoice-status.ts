/** Invoice status → badge variant (sprint-4/05). One source of truth shared by
 * the event Invoices tab, the global Invoices list, and the invoice detail. */
export type InvoiceBadgeVariant = 'secondary' | 'info' | 'success' | 'destructive' | 'warning';

const MAP: Record<string, InvoiceBadgeVariant> = {
  draft: 'secondary',
  issued: 'info',
  paid: 'success',
  'partially paid': 'warning',
  overdue: 'warning',
  cancelled: 'destructive',
  refunded: 'destructive',
};

export function invoiceStatusVariant(label: string | null | undefined): InvoiceBadgeVariant {
  return MAP[(label ?? '').toLowerCase()] ?? 'secondary';
}
