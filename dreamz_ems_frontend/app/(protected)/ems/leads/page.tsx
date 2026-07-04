'use client';

import { Fragment, useCallback, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';
import { Plus } from 'lucide-react';
import {
  Toolbar,
  ToolbarDescription,
  ToolbarHeading,
  ToolbarPageTitle,
} from '@/partials/common/toolbar';
import { Container } from '@/components/common/container';
import { ResourceList } from '@/components/platform/resource-list';
import { RequirePermission } from '@/components/common/require-permission';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { SearchSelect } from '@/components/platform/search-select';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { useStatusGraph } from '@/hooks/use-status-engine';
import { useCan } from '@/hooks/use-can';
import { emsService } from '@/services/ems-service';
import type { Client, Lead } from '@/types/ems';
import { useLeadsListConfig } from './use-leads-list-config';

const LEAD_ENTITY = 'lead';

export default function LeadsPage() {
  const router = useRouter();
  const engine = useStatusGraph(LEAD_ENTITY);
  const [creating, setCreating] = useState(false);
  const [bulkRows, setBulkRows] = useState<Lead[] | null>(null);
  const [convertRow, setConvertRow] = useState<Lead | null>(null);
  const [nonce, setNonce] = useState(0);

  const onCreate = useCallback(() => setCreating(true), []);
  const onEdit = useCallback((row: Lead) => router.push(`/ems/leads/${row.id}`), [router]);
  const onBulkStatus = useCallback((rows: Lead[]) => setBulkRows(rows), []);
  const onConvert = useCallback((row: Lead) => setConvertRow(row), []);

  const ctx = useMemo(
    () => ({
      onCreate,
      onEdit,
      onBulkStatus,
      onConvert,
      statuses: engine.graph?.statuses ?? [],
      transitions: engine.graph?.transitions ?? [],
    }),
    [onCreate, onEdit, onBulkStatus, onConvert, engine.graph],
  );
  const config = useLeadsListConfig(ctx);

  return (
    <RequirePermission permission="crm_leads.read">
      <Fragment>
        <Container width="fluid">
          <Toolbar>
            <ToolbarHeading>
              <ToolbarPageTitle />
              <ToolbarDescription>Your sales opportunities.</ToolbarDescription>
            </ToolbarHeading>
          </Toolbar>
        </Container>
        <Container width="fluid">
          <ResourceList key={nonce} config={config} />
        </Container>
        {creating && (
          <CreateLeadDialog
            onClose={() => setCreating(false)}
            onSaved={() => {
              setCreating(false);
              setNonce((n) => n + 1);
            }}
          />
        )}
        {bulkRows && (
          <BulkStatusDialog
            rows={bulkRows}
            statuses={(engine.graph?.statuses ?? []).map((s) => ({ value: s.id, label: s.label }))}
            onClose={() => setBulkRows(null)}
            onDone={() => {
              setBulkRows(null);
              setNonce((n) => n + 1);
            }}
          />
        )}
        {convertRow && (
          <ConvertLeadDialog
            lead={convertRow}
            onClose={() => setConvertRow(null)}
            onDone={(projectId) => {
              setConvertRow(null);
              setNonce((n) => n + 1);
              if (projectId) router.push(`/ems/events/${projectId}`);
            }}
          />
        )}
      </Fragment>
    </RequirePermission>
  );
}

/** Inline client picker with quick-create ("+ New"): load options, select, or
 * create a client without leaving the lead form (Cluster B reuse pattern). */
function ClientPicker({
  value,
  onChange,
}: {
  value: string | null;
  onChange: (id: string | null) => void;
}) {
  const { can } = useCan();
  const [clients, setClients] = useState<Client[]>([]);
  const [quick, setQuick] = useState(false);

  const reload = useCallback(
    (selectId?: string) => {
      emsService.clientOptions().then((rows) => {
        setClients(rows);
        if (selectId) onChange(selectId);
      });
    },
    [onChange],
  );

  useEffect(() => {
    reload();
  }, [reload]);

  return (
    <div className="space-y-1.5">
      <Label>Client</Label>
      <div className="flex items-center gap-2">
        <div className="flex-1">
          <SearchSelect
            value={value}
            onChange={(v) => onChange(v || null)}
            options={clients.map((c) => ({ value: c.id, label: c.name }))}
            placeholder="Link a client (optional)…"
          />
        </div>
        {can('crm_clients.manage') && (
          <Button type="button" variant="outline" size="sm" onClick={() => setQuick(true)}>
            <Plus className="size-4" /> New
          </Button>
        )}
      </div>
      {quick && (
        <QuickCreateClientDialog
          onClose={() => setQuick(false)}
          onCreated={(c) => {
            setQuick(false);
            reload(c.id);
          }}
        />
      )}
    </div>
  );
}

function QuickCreateClientDialog({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (client: Client) => void;
}) {
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const c = await emsService.createClient({ name });
      onCreated(c);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save.');
      setBusy(false);
    }
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>New client</DialogTitle>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="qc-name">Name *</Label>
            <Input id="qc-name" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
          </div>
          {error && <p className="text-destructive text-sm">{error}</p>}
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void save()} disabled={!name.trim() || busy}>
            {busy ? 'Saving…' : 'Create'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function CreateLeadDialog({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [title, setTitle] = useState('');
  const [source, setSource] = useState('');
  const [contactName, setContactName] = useState('');
  const [clientId, setClientId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await emsService.createLead({
        title,
        source: source || undefined,
        contactName: contactName || undefined,
        clientId: clientId || undefined,
      });
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save.');
      setBusy(false);
    }
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>New lead</DialogTitle>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="l-title">Title *</Label>
            <Input id="l-title" value={title} onChange={(e) => setTitle(e.target.value)} autoFocus />
          </div>
          <ClientPicker value={clientId} onChange={setClientId} />
          <div className="space-y-1.5">
            <Label htmlFor="l-source">Source</Label>
            <Input id="l-source" value={source} onChange={(e) => setSource(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="l-contact">Contact name</Label>
            <Input id="l-contact" value={contactName} onChange={(e) => setContactName(e.target.value)} />
          </div>
          {error && <p className="text-destructive text-sm">{error}</p>}
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void save()} disabled={!title.trim() || busy}>
            {busy ? 'Saving…' : 'Create'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ConvertLeadDialog({
  lead,
  onClose,
  onDone,
}: {
  lead: Lead;
  onClose: () => void;
  onDone: (projectId?: string) => void;
}) {
  const [templates, setTemplates] = useState<{ value: string; label: string }[]>([]);
  const [templateId, setTemplateId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    emsService
      .listTemplates({ pageSize: 200 })
      .then((p) => setTemplates(p.items.map((t) => ({ value: t.id, label: t.name }))))
      .catch(() => setTemplates([]));
  }, []);

  const convert = async () => {
    if (!templateId) return;
    setBusy(true);
    setError(null);
    try {
      const event = await emsService.createEventFromLead(lead.id, { templateId });
      toast.success('Event created from this lead.');
      onDone(event.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not create the event.');
      setBusy(false);
    }
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Create event — {lead.title}</DialogTitle>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <div className="space-y-1.5">
            <Label>Event template *</Label>
            <SearchSelect
              value={templateId}
              onChange={setTemplateId}
              options={templates}
              placeholder="Pick a template…"
              emptyText="No event templates yet"
            />
          </div>
          {error && <p className="text-destructive text-sm">{error}</p>}
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void convert()} disabled={!templateId || busy}>
            {busy ? 'Creating…' : 'Create event'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function BulkStatusDialog({
  rows,
  statuses,
  onClose,
  onDone,
}: {
  rows: Lead[];
  statuses: { value: string; label: string }[];
  onClose: () => void;
  onDone: () => void;
}) {
  const [toStatusId, setToStatusId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const apply = async () => {
    if (!toStatusId) return;
    setBusy(true);
    const results = await Promise.allSettled(
      rows.map((r) => emsService.transitionLead(r.id, toStatusId!)),
    );
    const ok = results.filter((r) => r.status === 'fulfilled').length;
    const failed = results.length - ok;
    if (ok) toast.success(`${ok} lead${ok === 1 ? '' : 's'} updated.`);
    if (failed) toast.error(`${failed} could not move to that status from their current state.`);
    onDone();
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Change status — {rows.length} selected</DialogTitle>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <div className="space-y-1.5">
            <Label>New status</Label>
            <SearchSelect value={toStatusId} onChange={setToStatusId} options={statuses} />
          </div>
          <p className="text-xs text-muted-foreground">
            Only leads whose current status allows the move are changed; the rest are skipped.
          </p>
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void apply()} disabled={!toStatusId || busy}>
            {busy ? 'Applying…' : 'Apply'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
