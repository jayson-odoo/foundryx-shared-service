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
import { useStatusGraph } from '@/hooks/use-status-engine';
import { emsService } from '@/services/ems-service';
import type { Profile } from '@/types/ems';
import { useProfilesListConfig } from './use-profiles-list-config';

const PROFILE_ENTITY = 'profile';

/** EMS Profiles on the Resource shell — list + detail/form view, tier-1 status
 * changes in the row/bulk/form, create + import. */
export default function ProfilesPage() {
  const router = useRouter();
  const engine = useStatusGraph(PROFILE_ENTITY);
  const [creating, setCreating] = useState(false);
  const [nonce, setNonce] = useState(0);

  const onCreate = useCallback(() => setCreating(true), []);
  const onEdit = useCallback((row: Profile) => router.push(`/ems/profiles/${row.id}`), [router]);

  const ctx = useMemo(
    () => ({
      onCreate,
      onEdit,
      statuses: engine.graph?.statuses ?? [],
      transitions: engine.graph?.transitions ?? [],
    }),
    [onCreate, onEdit, engine.graph],
  );
  const config = useProfilesListConfig(ctx);

  return (
    <RequirePermission permission="profiles.read">
      <Fragment>
        <Container width="fluid">
          <Toolbar>
            <ToolbarHeading>
              <ToolbarPageTitle />
              <ToolbarDescription>Participant identity across your events.</ToolbarDescription>
            </ToolbarHeading>
          </Toolbar>
        </Container>
        <Container width="fluid">
          <ResourceList key={nonce} config={config} />
        </Container>
        {creating && (
          <CreateProfileDialog
            onClose={() => setCreating(false)}
            onSaved={() => {
              setCreating(false);
              setNonce((n) => n + 1);
            }}
          />
        )}
      </Fragment>
    </RequirePermission>
  );
}

function CreateProfileDialog({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [email, setEmail] = useState('');
  const [fullName, setFullName] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await emsService.createProfile({ email, fullName: fullName || undefined });
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
          <DialogTitle>New profile</DialogTitle>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="p-email">Email *</Label>
            <Input id="p-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoFocus />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="p-name">Full name</Label>
            <Input id="p-name" value={fullName} onChange={(e) => setFullName(e.target.value)} />
          </div>
          {error && <p className="text-destructive text-sm">{error}</p>}
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void save()} disabled={!email.includes('@') || busy}>
            {busy ? 'Saving…' : 'Create'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
