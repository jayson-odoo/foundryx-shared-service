'use client';

import { Fragment, useCallback, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  Toolbar,
  ToolbarDescription,
  ToolbarHeading,
  ToolbarPageTitle,
} from '@/partials/common/toolbar';
import { Container } from '@/components/common/container';
import { ResourceList } from '@/components/platform/resource-list';
import { RequirePermission } from '@/components/common/require-permission';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useTerminology } from '@/hooks/use-terminology';
import { registrationService } from '@/services/registration-service';
import type { Venue } from '@/types/registration';
import { useVenuesListConfig } from './use-venues-list-config';

const VIEW_PERM = 'venues.read';

/** Venue master (sprint-4/05, Cluster D) — tenant-level reusable venues with
 * zones + a functional seat map. Resource shell; detail holds Zones + Seats. */
export default function VenuesPage() {
  const router = useRouter();
  const [creating, setCreating] = useState(false);
  const [nonce, setNonce] = useState(0);

  const onCreate = useCallback(() => setCreating(true), []);
  const onEdit = useCallback((row: Venue) => router.push(`/ems/venues/${row.id}`), [router]);
  const ctx = useMemo(() => ({ onCreate, onEdit }), [onCreate, onEdit]);
  const config = useVenuesListConfig(ctx);

  return (
    <RequirePermission permission={VIEW_PERM}>
      <Fragment>
        <Container width="fluid">
          <Toolbar>
            <ToolbarHeading>
              <ToolbarPageTitle />
              <ToolbarDescription>Reusable venues, zones and seat maps for your events.</ToolbarDescription>
            </ToolbarHeading>
          </Toolbar>
        </Container>
        <Container width="fluid">
          <ResourceList key={nonce} config={config} />
        </Container>
        {creating && (
          <CreateVenueDialog
            onClose={() => setCreating(false)}
            onSaved={(id) => {
              setCreating(false);
              setNonce((n) => n + 1);
              router.push(`/ems/venues/${id}`);
            }}
          />
        )}
      </Fragment>
    </RequirePermission>
  );
}

function CreateVenueDialog({ onClose, onSaved }: { onClose: () => void; onSaved: (id: string) => void }) {
  const { label } = useTerminology();
  const [name, setName] = useState('');
  const [address, setAddress] = useState('');
  const [capacity, setCapacity] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const v = await registrationService.createVenue({
        name,
        address: address || null,
        capacity: capacity === '' ? null : Number(capacity),
      });
      onSaved(v.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save.');
      setBusy(false);
    }
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>New {label('venue').toLowerCase()}</DialogTitle>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="vn-name">Name *</Label>
            <Input id="vn-name" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="vn-addr">Address</Label>
            <Input id="vn-addr" value={address} onChange={(e) => setAddress(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="vn-cap">Capacity</Label>
            <Input id="vn-cap" type="number" value={capacity} onChange={(e) => setCapacity(e.target.value)} />
          </div>
          {error && <p className="text-destructive text-sm">{error}</p>}
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button onClick={() => void save()} disabled={!name || busy}>{busy ? 'Saving…' : 'Create'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
