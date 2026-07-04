'use client';

import { Fragment, useCallback, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';
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
import { emsService } from '@/services/ems-service';
import type { Client } from '@/types/ems';
import { useClientsListConfig } from './use-clients-list-config';

const CLIENT_ENTITY = 'client';

export default function ClientsPage() {
  const router = useRouter();
  const engine = useStatusGraph(CLIENT_ENTITY);
  const [creating, setCreating] = useState(false);
  const [bulkRows, setBulkRows] = useState<Client[] | null>(null);
  const [nonce, setNonce] = useState(0);

  const onCreate = useCallback(() => setCreating(true), []);
  const onEdit = useCallback((row: Client) => router.push(`/ems/clients/${row.id}`), [router]);
  const onBulkStatus = useCallback((rows: Client[]) => setBulkRows(rows), []);

  const ctx = useMemo(
    () => ({
      onCreate,
      onEdit,
      onBulkStatus,
      statuses: engine.graph?.statuses ?? [],
      transitions: engine.graph?.transitions ?? [],
    }),
    [onCreate, onEdit, onBulkStatus, engine.graph],
  );
  const config = useClientsListConfig(ctx);

  return (
    <RequirePermission permission="crm_clients.read">
      <Fragment>
        <Container width="fluid">
          <Toolbar>
            <ToolbarHeading>
              <ToolbarPageTitle />
              <ToolbarDescription>Your B2B accounts.</ToolbarDescription>
            </ToolbarHeading>
          </Toolbar>
        </Container>
        <Container width="fluid">
          <ResourceList key={nonce} config={config} />
        </Container>
        {creating && (
          <CreateClientDialog
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
      </Fragment>
    </RequirePermission>
  );
}

function BulkStatusDialog({
  rows,
  statuses,
  onClose,
  onDone,
}: {
  rows: Client[];
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
      rows.map((r) => emsService.transitionClient(r.id, toStatusId!)),
    );
    const ok = results.filter((r) => r.status === 'fulfilled').length;
    const failed = results.length - ok;
    if (ok) toast.success(`${ok} client${ok === 1 ? '' : 's'} updated.`);
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
            Only clients whose current status allows the move are changed; the rest are skipped.
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

function CreateClientDialog({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState('');
  const [contactPerson, setContactPerson] = useState('');
  const [contactEmail, setContactEmail] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await emsService.createClient({
        name,
        contactPerson: contactPerson || undefined,
        contactEmail: contactEmail || undefined,
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
          <DialogTitle>New client</DialogTitle>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="c-name">Name *</Label>
            <Input id="c-name" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="c-person">Contact person</Label>
            <Input id="c-person" value={contactPerson} onChange={(e) => setContactPerson(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="c-email">Contact email</Label>
            <Input id="c-email" type="email" value={contactEmail} onChange={(e) => setContactEmail(e.target.value)} />
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
