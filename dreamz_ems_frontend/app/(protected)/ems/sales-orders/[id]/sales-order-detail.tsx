'use client';

/** Sales-order detail/form — header (client/currency/notes) + a line-item table
 * (qty/unit/amount + invoiced/remaining) + a "Create invoice from SO" action that
 * opens a per-line qty picker (only invoiceable lines shown) → mints a finance
 * invoice and links to it. Status moves live in the form "…". */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useForm } from 'react-hook-form';
import { ArrowRight, FileText, Info, LoaderCircleIcon, Receipt } from 'lucide-react';
import { toast } from 'sonner';
import { Container } from '@/components/common/container';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Form } from '@/components/ui/form';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { SearchSelect } from '@/components/platform/search-select';
import { ResourceForm } from '@/components/platform/resource-form';
import type { ResourceFormConfig } from '@/components/platform/resource-form/types';
import type { ResourceAction } from '@/components/platform/resource-list';
import { useStatusGraph } from '@/hooks/use-status-engine';
import { useTerminology } from '@/hooks/use-terminology';
import { emsService } from '@/services/ems-service';
import { CURRENCY_OPTIONS, formatMoney } from '@/lib/money';
import type { Client, InvoiceLineSelection, SalesOrder, SalesOrderLine } from '@/types/ems';

const SALES_ORDER_ENTITY = 'sales_order';

interface HeaderValues {
  currency: string;
  notes: string;
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-1.5 md:grid-cols-[160px_1fr] md:items-start md:gap-4">
      <Label className="pt-2 text-sm text-muted-foreground">{label}</Label>
      <div className="max-w-2xl">{children}</div>
    </div>
  );
}

const remaining = (l: SalesOrderLine) => (Number(l.qty) || 0) - (Number(l.invoicedQty) || 0);

export function SalesOrderDetail({ salesOrderId }: { salesOrderId: string }) {
  const router = useRouter();
  const { labelPlural } = useTerminology();
  const engine = useStatusGraph(SALES_ORDER_ENTITY);
  const form = useForm<HeaderValues>({ defaultValues: { currency: '', notes: '' } });

  const [record, setRecord] = useState<SalesOrder | null>(null);
  const [clients, setClients] = useState<Client[]>([]);
  const [loading, setLoading] = useState(true);
  const [invoiceOpen, setInvoiceOpen] = useState(false);

  const load = useCallback(() => {
    return emsService.getSalesOrder(salesOrderId).then((so) => {
      setRecord(so);
      form.reset({ currency: so.currency ?? '', notes: so.notes ?? '' });
    });
  }, [salesOrderId, form]);

  useEffect(() => {
    let active = true;
    load().finally(() => active && setLoading(false));
    emsService.clientOptions().then((r) => active && setClients(r));
    return () => {
      active = false;
    };
  }, [load]);

  const values = form.watch();
  const dirty = form.formState.isDirty;

  const statusKey = useMemo(
    () => engine.graph?.statuses.find((s) => s.id === record?.statusId)?.key ?? '',
    [engine.graph, record?.statusId],
  );
  const statusLabel = useMemo(
    () => engine.graph?.statuses.find((s) => s.id === record?.statusId)?.label ?? '',
    [engine.graph, record?.statusId],
  );
  const isDraft = statusKey === 'draft';
  const isConfirmed = statusKey === 'confirmed';
  const clientName = clients.find((c) => c.id === record?.clientId)?.name ?? record?.clientId ?? '';

  const config = useMemo<ResourceFormConfig<SalesOrder> | null>(() => {
    if (!record) return null;
    const moves = record.statusId
      ? (engine.graph?.transitions ?? []).filter((t) => t.fromStatusId === record.statusId)
      : [];
    const statusName = (id: string) => engine.graph?.statuses.find((s) => s.id === id)?.label ?? id;

    const actions: ResourceAction<SalesOrder>[] = [
      ...(isConfirmed
        ? [
            {
              id: 'create-invoice',
              label: 'Create invoice',
              icon: Receipt,
              surfaces: { row: false, form: true, bulk: false },
              permission: 'crm_sales_orders.manage',
              run: () => setInvoiceOpen(true),
            } as ResourceAction<SalesOrder>,
          ]
        : []),
      ...moves.map((t) => ({
        id: `move-${t.toStatusId}`,
        label: statusName(t.toStatusId),
        icon: ArrowRight,
        surfaces: { row: false, form: true, bulk: false },
        permission: 'crm_sales_orders.manage',
        run: async (_rows: SalesOrder[], runtime: { reload: () => void }) => {
          try {
            await emsService.transitionSalesOrder(record.id, t.toStatusId);
            runtime.reload();
          } catch (e) {
            toast.error(e instanceof Error ? e.message : 'Could not change the status.');
          }
        },
      })),
    ];

    const title = record.docNumber ? record.docNumber : `${clientName} · Draft`;

    return {
      breadcrumb: [{ label: labelPlural('sales_order'), href: '/ems/sales-orders' }, { label: title }],
      backHref: '/ems/sales-orders',
      backLabel: labelPlural('sales_order'),
      title,
      tabs: [
        {
          id: 'details',
          label: 'Details',
          icon: Info,
          render: ({ editing }) => (
            <div className="flex flex-col gap-5 py-2">
              <Row label="Status">
                {statusLabel ? (
                  <Badge variant="primary" appearance="light" size="sm">{statusLabel}</Badge>
                ) : (
                  <span className="text-sm text-muted-foreground">—</span>
                )}
              </Row>
              <Row label="Client">
                <span className="text-sm">{clientName}</span>
              </Row>
              {record.quotationId && (
                <Row label="Quotation">
                  <span className="text-sm text-muted-foreground">{record.quotationId}</span>
                </Row>
              )}
              <Row label="Currency">
                {editing && isDraft ? (
                  <div className="max-w-32">
                    <SearchSelect value={values.currency || null} onChange={(v) => form.setValue('currency', v || '', { shouldDirty: true })} options={CURRENCY_OPTIONS} />
                  </div>
                ) : (
                  <span className="text-sm">{values.currency || '—'}</span>
                )}
              </Row>
              <Row label="Notes">
                {editing ? (
                  <Input value={values.notes} onChange={(e) => form.setValue('notes', e.target.value, { shouldDirty: true })} />
                ) : (
                  <span className="text-sm">{values.notes || '—'}</span>
                )}
              </Row>
            </div>
          ),
        },
        {
          id: 'lines',
          label: 'Lines',
          icon: FileText,
          render: () => <LinesTable lines={record.lines} currency={record.currency} />,
        },
      ],
      actions,
      actionRows: [record],
      onReload: () => load(),
      editable: true,
      editPermission: 'crm_sales_orders.manage',
      isDirty: dirty,
      onSave: async () => {
        const updated = await emsService.updateSalesOrder(record.id, {
          currency: values.currency || null,
          notes: values.notes || null,
        });
        setRecord(updated);
        form.reset({ currency: updated.currency ?? '', notes: updated.notes ?? '' });
        return true;
      },
      onCancel: () => {
        form.reset({ currency: record.currency ?? '', notes: record.notes ?? '' });
      },
    };
  }, [record, engine.graph, values, form, clientName, statusLabel, isDraft, isConfirmed, dirty, labelPlural, load]);

  if (loading || engine.loading) {
    return (
      <Container width="fluid">
        <div className="flex items-center justify-center py-24 text-muted-foreground">
          <LoaderCircleIcon className="size-6 animate-spin" />
        </div>
      </Container>
    );
  }
  if (!config || !record) {
    return (
      <Container width="fluid">
        <div className="py-24 text-center text-sm font-medium">Sales order not found.</div>
      </Container>
    );
  }
  return (
    <Container width="fluid">
      <Form {...form}>
        <ResourceForm config={config} />
      </Form>
      <CreateInvoiceDialog
        open={invoiceOpen}
        onOpenChange={setInvoiceOpen}
        salesOrder={record}
        onCreated={() => {
          setInvoiceOpen(false);
          void load();
          toast.success('Invoice created.');
          router.push('/finance/invoices');
        }}
      />
    </Container>
  );
}

function LinesTable({ lines, currency }: { lines: SalesOrderLine[]; currency: string | null }) {
  const total = lines.reduce((s, l) => s + (Number(l.amount) || 0), 0);
  return (
    <div className="rounded-xl border border-border">
      <div className="border-b border-border px-4 py-2.5 text-sm font-medium">Line items</div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-muted-foreground">
              <th className="px-3 py-2 text-start font-medium">Description</th>
              <th className="px-3 py-2 text-end font-medium">Qty</th>
              <th className="px-3 py-2 text-end font-medium">Unit price</th>
              <th className="px-3 py-2 text-end font-medium">Amount</th>
              <th className="px-3 py-2 text-end font-medium">Invoiced</th>
            </tr>
          </thead>
          <tbody>
            {lines.length === 0 && (
              <tr>
                <td colSpan={5} className="px-3 py-6 text-center text-muted-foreground">No line items.</td>
              </tr>
            )}
            {lines.map((l) => (
              <tr key={l.id} className="border-t border-border align-top">
                <td className="px-3 py-2 min-w-44">{l.description || '—'}</td>
                <td className="px-3 py-2 text-end">{l.qty}</td>
                <td className="px-3 py-2 text-end">{formatMoney(Number(l.unitPrice), currency)}</td>
                <td className="px-3 py-2 text-end font-medium">{formatMoney(Number(l.amount), currency)}</td>
                <td className="px-3 py-2 text-end text-muted-foreground">
                  {Number(l.invoicedQty) || 0} / {l.qty}
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="border-t border-border">
              <td colSpan={3} className="px-3 py-2.5 text-end text-sm font-medium">Total</td>
              <td className="px-3 py-2.5 text-end text-sm font-semibold">{formatMoney(total, currency)}</td>
              <td />
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  );
}

function CreateInvoiceDialog({
  open,
  onOpenChange,
  salesOrder,
  onCreated,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  salesOrder: SalesOrder;
  onCreated: (invoiceId: string) => void;
}) {
  // Foolproof-UI: only lines with remaining qty are invoiceable.
  const invoiceable = useMemo(() => salesOrder.lines.filter((l) => remaining(l) > 0), [salesOrder.lines]);
  const [qtys, setQtys] = useState<Record<string, number>>({});
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) {
      setQtys(Object.fromEntries(invoiceable.map((l) => [l.id!, remaining(l)])));
    }
  }, [open, invoiceable]);

  const selections: InvoiceLineSelection[] = invoiceable
    .map((l) => ({ lineId: l.id!, qty: Number(qtys[l.id!]) || 0 }))
    .filter((s) => s.qty > 0);

  const submit = async () => {
    if (selections.length === 0) return;
    setBusy(true);
    try {
      const inv = await emsService.createInvoiceFromSalesOrder(salesOrder.id, selections);
      onCreated(inv.id);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not create the invoice.');
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Create invoice from sales order</DialogTitle>
        </DialogHeader>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-muted-foreground">
                <th className="px-2 py-2 text-start font-medium">Line</th>
                <th className="px-2 py-2 text-end font-medium">Remaining</th>
                <th className="px-2 py-2 text-end font-medium">Invoice qty</th>
              </tr>
            </thead>
            <tbody>
              {invoiceable.length === 0 && (
                <tr>
                  <td colSpan={3} className="px-2 py-6 text-center text-muted-foreground">
                    Every line is fully invoiced.
                  </td>
                </tr>
              )}
              {invoiceable.map((l) => (
                <tr key={l.id} className="border-t border-border">
                  <td className="px-2 py-2">{l.description || '—'}</td>
                  <td className="px-2 py-2 text-end text-muted-foreground">{remaining(l)}</td>
                  <td className="px-2 py-2 text-end">
                    <div className="flex justify-end">
                      <Input
                        type="number"
                        min={0}
                        max={remaining(l)}
                        step={1}
                        className="w-24 text-end"
                        value={String(qtys[l.id!] ?? 0)}
                        onChange={(e) =>
                          setQtys((prev) => ({
                            ...prev,
                            [l.id!]: Math.max(0, Math.min(remaining(l), Number(e.target.value) || 0)),
                          }))
                        }
                      />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void submit()} disabled={selections.length === 0 || busy}>
            {busy ? 'Creating…' : 'Create invoice'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
