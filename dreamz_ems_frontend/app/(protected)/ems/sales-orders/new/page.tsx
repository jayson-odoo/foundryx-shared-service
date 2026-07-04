'use client';

/** Dedicated sales-order create page — from an accepted quotation OR from
 * scratch (client + currency). */
import { Fragment, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';
import {
  Toolbar,
  ToolbarActions,
  ToolbarDescription,
  ToolbarHeading,
  ToolbarPageTitle,
} from '@/partials/common/toolbar';
import { Container } from '@/components/common/container';
import { RequirePermission } from '@/components/common/require-permission';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { SearchSelect } from '@/components/platform/search-select';
import { useStatusGraph } from '@/hooks/use-status-engine';
import { emsService } from '@/services/ems-service';
import { CURRENCY_OPTIONS } from '@/lib/money';
import type { Client, Quotation } from '@/types/ems';

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-1.5 md:grid-cols-[200px_1fr] md:items-start md:gap-4">
      <Label className="pt-2 text-sm text-muted-foreground">{label}</Label>
      <div className="max-w-xl">{children}</div>
    </div>
  );
}

type Mode = 'quotation' | 'scratch';

function NewSalesOrderForm() {
  const router = useRouter();
  const quotationEngine = useStatusGraph('quotation');
  const [mode, setMode] = useState<Mode>('quotation');
  const [clients, setClients] = useState<Client[]>([]);
  const [quotations, setQuotations] = useState<Quotation[]>([]);
  const [clientId, setClientId] = useState<string | null>(null);
  const [quotationId, setQuotationId] = useState<string | null>(null);
  const [currency, setCurrency] = useState('USD');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    emsService.clientOptions().then(setClients).catch(() => setClients([]));
    emsService
      .listQuotationsQuery({ page: 0, pageSize: 200, statusView: 'active' })
      .then((r) => setQuotations(r.data))
      .catch(() => setQuotations([]));
    emsService.getTenantSettings().then((s) => setCurrency(s.defaultCurrency)).catch(() => undefined);
  }, []);

  // Foolproof-UI: only ACCEPTED quotations can become a sales order.
  const acceptedStatusId = useMemo(
    () => quotationEngine.graph?.statuses.find((s) => s.key === 'accepted')?.id ?? null,
    [quotationEngine.graph],
  );
  const acceptedQuotations = useMemo(
    () => (acceptedStatusId ? quotations.filter((q) => q.statusId === acceptedStatusId) : []),
    [quotations, acceptedStatusId],
  );
  const clientName = (id: string) => clients.find((c) => c.id === id)?.name ?? id;

  const canSave = mode === 'quotation' ? !!quotationId : !!clientId;

  const save = async () => {
    setBusy(true);
    try {
      const so =
        mode === 'quotation' && quotationId
          ? await emsService.createSalesOrderFromQuotation(quotationId)
          : await emsService.createSalesOrder({ clientId: clientId ?? undefined, currency: currency || undefined, lines: [] });
      toast.success('Sales order created.');
      router.push(`/ems/sales-orders/${so.id}`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not create the sales order.');
      setBusy(false);
    }
  };

  return (
    <Fragment>
      <Container width="fluid">
        <Toolbar>
          <ToolbarHeading>
            <ToolbarPageTitle text="New sales order" />
            <ToolbarDescription>Confirm a commercial order.</ToolbarDescription>
          </ToolbarHeading>
          <ToolbarActions>
            <Button variant="outline" onClick={() => router.push('/ems/sales-orders')} disabled={busy}>
              Cancel
            </Button>
            <Button onClick={() => void save()} disabled={!canSave || busy}>
              {busy ? 'Creating…' : 'Create'}
            </Button>
          </ToolbarActions>
        </Toolbar>
      </Container>
      <Container width="fluid">
        <Card>
          <CardContent className="flex flex-col gap-5 py-5">
            <Tabs value={mode} onValueChange={(v) => setMode(v as Mode)}>
              <TabsList>
                <TabsTrigger value="quotation">From quotation</TabsTrigger>
                <TabsTrigger value="scratch">From scratch</TabsTrigger>
              </TabsList>
            </Tabs>

            {mode === 'quotation' ? (
              <Row label="Accepted quotation *">
                <SearchSelect
                  value={quotationId}
                  onChange={(v) => setQuotationId(v || null)}
                  options={acceptedQuotations.map((q) => ({
                    value: q.id,
                    label: `${clientName(q.clientId)} · v${q.revisionNumber}`,
                  }))}
                  placeholder="Select an accepted quotation…"
                />
              </Row>
            ) : (
              <Fragment>
                <Row label="Client *">
                  <SearchSelect
                    value={clientId}
                    onChange={(v) => setClientId(v || null)}
                    options={clients.map((c) => ({ value: c.id, label: c.name }))}
                    placeholder="Select a client…"
                  />
                </Row>
                <Row label="Currency">
                  <div className="w-40">
                    <SearchSelect value={currency} onChange={(v) => setCurrency(v || 'USD')} options={CURRENCY_OPTIONS} />
                  </div>
                </Row>
              </Fragment>
            )}
          </CardContent>
        </Card>
      </Container>
    </Fragment>
  );
}

export default function NewSalesOrderPage() {
  return (
    <RequirePermission permission="crm_sales_orders.manage">
      <NewSalesOrderForm />
    </RequirePermission>
  );
}
