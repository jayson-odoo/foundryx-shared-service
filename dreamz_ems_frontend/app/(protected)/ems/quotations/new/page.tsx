'use client';

/** Dedicated quotation create page (sprint-4/08) — replaces the create popup. */
import { Fragment, useEffect, useState } from 'react';
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
import { SearchSelect } from '@/components/platform/search-select';
import { emsService } from '@/services/ems-service';
import { CURRENCY_OPTIONS } from '@/lib/money';
import type { Client, Lead } from '@/types/ems';

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-1.5 md:grid-cols-[200px_1fr] md:items-start md:gap-4">
      <Label className="pt-2 text-sm text-muted-foreground">{label}</Label>
      <div className="max-w-xl">{children}</div>
    </div>
  );
}

function NewQuotationForm() {
  const router = useRouter();
  const [clients, setClients] = useState<Client[]>([]);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [clientId, setClientId] = useState<string | null>(null);
  const [leadId, setLeadId] = useState<string | null>(null);
  const [currency, setCurrency] = useState('USD');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    emsService.clientOptions().then(setClients).catch(() => setClients([]));
    emsService
      .listLeadsQuery({ page: 0, pageSize: 100, statusView: 'active' })
      .then((r) => setLeads(r.data))
      .catch(() => setLeads([]));
    emsService.getTenantSettings().then((s) => setCurrency(s.defaultCurrency)).catch(() => undefined);
  }, []);

  const onPickLead = (id: string | null) => {
    setLeadId(id);
    const lead = leads.find((l) => l.id === id);
    if (lead?.clientId) setClientId(lead.clientId);
  };

  const save = async () => {
    if (!clientId || !leadId) return;
    setBusy(true);
    try {
      const q = await emsService.createQuotation({ clientId, leadId, currency: currency || undefined, lines: [] });
      toast.success('Quotation created.');
      router.push(`/ems/quotations/${q.id}`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not create the quotation.');
      setBusy(false);
    }
  };

  return (
    <Fragment>
      <Container width="fluid">
        <Toolbar>
          <ToolbarHeading>
            <ToolbarPageTitle text="New quotation" />
            <ToolbarDescription>Raise a B2B service quote against a lead.</ToolbarDescription>
          </ToolbarHeading>
          <ToolbarActions>
            <Button variant="outline" onClick={() => router.push('/ems/quotations')} disabled={busy}>
              Cancel
            </Button>
            <Button onClick={() => void save()} disabled={!clientId || !leadId || busy}>
              {busy ? 'Creating…' : 'Create'}
            </Button>
          </ToolbarActions>
        </Toolbar>
      </Container>
      <Container width="fluid">
        <Card>
          <CardContent className="flex flex-col gap-5 py-5">
            <Row label="Lead *">
              <SearchSelect value={leadId} onChange={onPickLead} options={leads.map((l) => ({ value: l.id, label: l.title }))} placeholder="Raise against a lead…" />
            </Row>
            <Row label="Client *">
              <SearchSelect value={clientId} onChange={(v) => setClientId(v || null)} options={clients.map((c) => ({ value: c.id, label: c.name }))} placeholder="Select a client…" />
            </Row>
            <Row label="Currency">
              <div className="w-40">
                <SearchSelect value={currency} onChange={(v) => setCurrency(v || 'USD')} options={CURRENCY_OPTIONS} />
              </div>
            </Row>
          </CardContent>
        </Card>
      </Container>
    </Fragment>
  );
}

export default function NewQuotationPage() {
  return (
    <RequirePermission permission="crm_quotations.manage">
      <NewQuotationForm />
    </RequirePermission>
  );
}
