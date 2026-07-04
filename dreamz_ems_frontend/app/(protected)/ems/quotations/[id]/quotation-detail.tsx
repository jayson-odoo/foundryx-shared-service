'use client';

/** Quotation detail/form — header (client/lead/currency/notes) + a line-item
 * editor (product picker autofills price; qty × unit = amount; derived total) +
 * a Documents tab that attaches Drive files via core /documents/file-links.
 * Status moves + Revise live in the form "…". */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useForm } from 'react-hook-form';
import { ArrowRight, Copy, History, Info, LoaderCircleIcon, Paperclip, Plus, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import { Container } from '@/components/common/container';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Form } from '@/components/ui/form';
import { SearchSelect } from '@/components/platform/search-select';
import { ResourceForm } from '@/components/platform/resource-form';
import type { ResourceFormConfig } from '@/components/platform/resource-form/types';
import { ResourceList, type ResourceAction } from '@/components/platform/resource-list';
import { embeddedListConfig } from '@/components/platform/resource-list/embedded-list-config';
import { useStatusGraph } from '@/hooks/use-status-engine';
import { useTerminology } from '@/hooks/use-terminology';
import { emsService } from '@/services/ems-service';
import { CURRENCY_OPTIONS, formatMoney } from '@/lib/money';
import type { Client, Product, Quotation, QuotationLine } from '@/types/ems';
import { AttachPanel } from './attach-panel';

const QUOTATION_ENTITY = 'quotation';

type LineDraft = QuotationLine & { _rid: string };

let _rc = 0;
const rid = () => `ln-${_rc++}`;

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

export function QuotationDetail({ quotationId }: { quotationId: string }) {
  const router = useRouter();
  const { labelPlural } = useTerminology();
  const engine = useStatusGraph(QUOTATION_ENTITY);
  const form = useForm<HeaderValues>({ defaultValues: { currency: '', notes: '' } });

  const [record, setRecord] = useState<Quotation | null>(null);
  const [clients, setClients] = useState<Client[]>([]);
  const [products, setProducts] = useState<Product[]>([]);
  const [lines, setLines] = useState<LineDraft[]>([]);
  const [linesDirty, setLinesDirty] = useState(false);
  const [decimals, setDecimals] = useState(2);
  const [loading, setLoading] = useState(true);

  const resetLines = useCallback((q: Quotation) => {
    setLines(q.lines.map((l) => ({ ...l, _rid: rid() })));
    setLinesDirty(false);
  }, []);

  const load = useCallback(() => {
    return emsService.getQuotation(quotationId).then((q) => {
      setRecord(q);
      form.reset({ currency: q.currency ?? '', notes: q.notes ?? '' });
      resetLines(q);
    });
  }, [quotationId, form, resetLines]);

  useEffect(() => {
    let active = true;
    load().finally(() => active && setLoading(false));
    emsService.clientOptions().then((r) => active && setClients(r));
    emsService.productOptions().then((r) => active && setProducts(r));
    emsService.getTenantSettings().then((s) => active && setDecimals(s.priceDecimals)).catch(() => undefined);
    return () => {
      active = false;
    };
  }, [load]);

  const values = form.watch();
  const total = useMemo(
    () => Math.round(lines.reduce((s, l) => s + (Number(l.qty) || 0) * (Number(l.unitPrice) || 0), 0) * 100) / 100,
    [lines],
  );
  const dirty = form.formState.isDirty || linesDirty;

  const setLine = useCallback((rid_: string, patch: Partial<LineDraft>) => {
    setLines((prev) => prev.map((l) => (l._rid === rid_ ? { ...l, ...patch } : l)));
    setLinesDirty(true);
  }, []);
  const addLine = useCallback(() => {
    setLines((prev) => [...prev, { _rid: rid(), productId: null, description: '', qty: 1, unitPrice: 0 }]);
    setLinesDirty(true);
  }, []);
  const removeLine = useCallback((rid_: string) => {
    setLines((prev) => prev.filter((l) => l._rid !== rid_));
    setLinesDirty(true);
  }, []);
  const onPickProduct = useCallback(
    (rid_: string, productId: string | null) => {
      const p = products.find((x) => x.id === productId);
      setLines((prev) =>
        prev.map((l) =>
          l._rid === rid_
            ? {
                ...l,
                productId,
                ...(p ? { unitPrice: p.defaultPrice ?? 0 } : {}),
                ...(p && !l.description ? { description: p.name } : {}),
              }
            : l,
        ),
      );
      setLinesDirty(true);
    },
    [products],
  );

  const statusLabel = useMemo(
    () => engine.graph?.statuses.find((s) => s.id === record?.statusId)?.label ?? '',
    [engine.graph, record?.statusId],
  );

  const config = useMemo<ResourceFormConfig<Quotation> | null>(() => {
    if (!record) return null;
    const moves = record.statusId
      ? (engine.graph?.transitions ?? []).filter((t) => t.fromStatusId === record.statusId)
      : [];
    const statusName = (id: string) => engine.graph?.statuses.find((s) => s.id === id)?.label ?? id;
    const clientName = clients.find((c) => c.id === record.clientId)?.name ?? record.clientId;

    const actions: ResourceAction<Quotation>[] = [
      ...moves.map((t) => ({
        id: `move-${t.toStatusId}`,
        label: statusName(t.toStatusId),
        icon: ArrowRight,
        surfaces: { row: false, form: true, bulk: false },
        permission: 'crm_quotations.manage',
        run: async (_rows: Quotation[], runtime: { reload: () => void }) => {
          try {
            await emsService.transitionQuotation(record.id, t.toStatusId);
            runtime.reload();
          } catch (e) {
            toast.error(e instanceof Error ? e.message : 'Could not change the status.');
          }
        },
      })),
      {
        id: 'revise',
        label: 'Revise',
        icon: Copy,
        surfaces: { row: false, form: true, bulk: false },
        permission: 'crm_quotations.manage',
        run: async () => {
          try {
            const rev = await emsService.reviseQuotation(record.id);
            toast.success(`Revision ${rev.revisionNumber} created.`);
            router.push(`/ems/quotations/${rev.id}`);
          } catch (e) {
            toast.error(e instanceof Error ? e.message : 'Could not revise.');
          }
        },
      },
    ];

    return {
      breadcrumb: [{ label: labelPlural('quotation'), href: '/ems/quotations' }, { label: `${clientName} · v${record.revisionNumber}` }],
      backHref: '/ems/quotations',
      backLabel: labelPlural('quotation'),
      title: `${clientName} · v${record.revisionNumber}`,
      subtitle: record.parentQuotationId ? 'Revision' : undefined,
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
              <Row label="Currency">
                {editing ? (
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
              <div className="pt-2">
                <LinesEditor
                  editing={editing}
                  lines={lines}
                  products={products}
                  currency={values.currency}
                  total={total}
                  decimals={decimals}
                  onPickProduct={onPickProduct}
                  onSetLine={setLine}
                  onAddLine={addLine}
                  onRemoveLine={removeLine}
                />
              </div>
            </div>
          ),
        },
        {
          id: 'revisions',
          label: 'Revisions',
          icon: History,
          render: () => <RelatedRevisions quotationId={record.id} />,
        },
        {
          id: 'documents',
          label: 'Documents',
          icon: Paperclip,
          render: () => <AttachPanel entityType="quotation" entityId={record.id} />,
        },
      ],
      actions,
      actionRows: [record],
      onReload: () => load(),
      editable: true,
      editPermission: 'crm_quotations.manage',
      isDirty: dirty,
      onSave: async () => {
        const updated = await emsService.updateQuotation(record.id, {
          currency: values.currency || null,
          notes: values.notes || null,
          lines: lines.map((l, i) => ({
            productId: l.productId,
            description: l.description,
            qty: Number(l.qty) || 0,
            unitPrice: Number(l.unitPrice) || 0,
            sort: i,
          })),
        });
        setRecord(updated);
        form.reset({ currency: updated.currency ?? '', notes: updated.notes ?? '' });
        resetLines(updated);
        return true;
      },
      onCancel: () => {
        form.reset({ currency: record.currency ?? '', notes: record.notes ?? '' });
        resetLines(record);
      },
    };
  }, [record, engine.graph, values, form, lines, products, clients, total, decimals, statusLabel, dirty, labelPlural, load, resetLines, router, onPickProduct, setLine, addLine, removeLine]);

  if (loading || engine.loading) {
    return (
      <Container width="fluid">
        <div className="flex items-center justify-center py-24 text-muted-foreground">
          <LoaderCircleIcon className="size-6 animate-spin" />
        </div>
      </Container>
    );
  }
  if (!config) {
    return (
      <Container width="fluid">
        <div className="py-24 text-center text-sm font-medium">Quotation not found.</div>
      </Container>
    );
  }
  return (
    <Container width="fluid">
      <Form {...form}>
        <ResourceForm config={config} />
      </Form>
    </Container>
  );
}

function LinesEditor({
  editing,
  lines,
  products,
  currency,
  total,
  decimals,
  onPickProduct,
  onSetLine,
  onAddLine,
  onRemoveLine,
}: {
  editing: boolean;
  lines: LineDraft[];
  products: Product[];
  currency: string;
  total: number;
  decimals: number;
  onPickProduct: (rid: string, productId: string | null) => void;
  onSetLine: (rid: string, patch: Partial<LineDraft>) => void;
  onAddLine: () => void;
  onRemoveLine: (rid: string) => void;
}) {
  const productOptions = products.map((p) => ({ value: p.id, label: p.name }));
  const fmt = (n: number) => (Number(n) || 0).toFixed(decimals);
  const step = decimals > 0 ? 1 / 10 ** decimals : 1;
  return (
    <div className="rounded-xl border border-border">
      <div className="border-b border-border px-4 py-2.5 text-sm font-medium">Line items</div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-muted-foreground">
              <th className="px-3 py-2 text-start font-medium">Product</th>
              <th className="px-3 py-2 text-start font-medium">Description</th>
              <th className="px-3 py-2 text-end font-medium">Qty</th>
              <th className="px-3 py-2 text-end font-medium">Unit price</th>
              <th className="px-3 py-2 text-end font-medium">Amount</th>
              {editing && <th className="w-10" />}
            </tr>
          </thead>
          <tbody>
            {lines.length === 0 && (
              <tr>
                <td colSpan={editing ? 6 : 5} className="px-3 py-6 text-center text-muted-foreground">
                  No line items yet.
                </td>
              </tr>
            )}
            {lines.map((l) => {
              const amount = Math.round((Number(l.qty) || 0) * (Number(l.unitPrice) || 0) * 100) / 100;
              return (
                <tr key={l._rid} className="border-t border-border align-top">
                  <td className="px-3 py-2 min-w-44">
                    {editing ? (
                      <SearchSelect
                        value={l.productId}
                        onChange={(v) => onPickProduct(l._rid, v || null)}
                        options={productOptions}
                        placeholder="Free-form"
                      />
                    ) : (
                      <span>{products.find((p) => p.id === l.productId)?.name ?? '—'}</span>
                    )}
                  </td>
                  <td className="px-3 py-2 min-w-44">
                    {editing ? (
                      <Input
                        value={l.description ?? ''}
                        onChange={(e) => onSetLine(l._rid, { description: e.target.value })}
                      />
                    ) : (
                      <span>{l.description || '—'}</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-end">
                    {editing ? (
                      <div className="flex justify-end">
                        <Input
                          type="number"
                          className="w-28 text-end"
                          value={String(l.qty)}
                          onChange={(e) => onSetLine(l._rid, { qty: Number(e.target.value) })}
                        />
                      </div>
                    ) : (
                      l.qty
                    )}
                  </td>
                  <td className="px-3 py-2 text-end">
                    {editing ? (
                      <div className="flex justify-end">
                        <Input
                          type="number"
                          step={step}
                          className="w-28 text-end"
                          value={String(l.unitPrice)}
                          onChange={(e) => onSetLine(l._rid, { unitPrice: Number(e.target.value) })}
                        />
                      </div>
                    ) : (
                      fmt(Number(l.unitPrice))
                    )}
                  </td>
                  <td className="px-3 py-2 text-end font-medium">{fmt(amount)}</td>
                  {editing && (
                    <td className="px-2 py-2 text-end">
                      <Button variant="ghost" size="sm" aria-label="Remove line" onClick={() => onRemoveLine(l._rid)}>
                        <Trash2 className="size-4" />
                      </Button>
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
          <tfoot>
            <tr className="border-t border-border">
              <td colSpan={editing ? 4 : 3} className="px-3 py-2.5 text-end text-sm font-medium">
                Total
              </td>
              <td className="px-3 py-2.5 text-end text-sm font-semibold">
                {currency ? `${currency} ` : ''}
                {fmt(total)}
              </td>
              {editing && <td />}
            </tr>
          </tfoot>
        </table>
      </div>
      {editing && (
        <div className="border-t border-border px-3 py-2">
          <Button variant="outline" size="sm" onClick={onAddLine}>
            <Plus className="size-4" /> Add line
          </Button>
        </div>
      )}
    </div>
  );
}

function RelatedRevisions({ quotationId }: { quotationId: string }) {
  const config = useMemo(
    () =>
      embeddedListConfig<Quotation>({
        viewKey: 'quotation_revisions',
        getRowId: (r) => r.id,
        rowHref: (r) => `/ems/quotations/${r.id}`,
        defaultSort: { id: 'revisionNumber', desc: true },
        fetcher: async () => {
          const rows = await emsService.quotationRevisions(quotationId);
          return { data: rows, total: rows.length, page: 0 };
        },
        columns: [
          { id: 'revisionNumber', accessorKey: 'revisionNumber', header: 'Rev', cell: ({ row }) => <span className="font-medium">v{row.original.revisionNumber}</span> },
          { id: 'total', accessorKey: 'total', header: 'Total', cell: ({ row }) => <span>{formatMoney(row.original.total, row.original.currency)}</span> },
        ],
      }),
    [quotationId],
  );
  return <ResourceList config={config} />;
}
