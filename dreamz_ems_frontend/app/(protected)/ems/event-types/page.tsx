'use client';

import { Fragment, useState } from 'react';
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
import { Textarea } from '@/components/ui/textarea';
import { useTerminology } from '@/hooks/use-terminology';
import { emsService } from '@/services/ems-service';
import type { ProjectType } from '@/types/ems';
import { useEventTypesListConfig } from './use-event-types-list-config';

/** EMS Event Types on the Resource shell — create / edit / delete the category
 * master data that templates hang off. */
export default function EventTypesPage() {
  const [editing, setEditing] = useState<ProjectType | 'new' | null>(null);
  const [nonce, setNonce] = useState(0);
  const config = useEventTypesListConfig(
    () => setEditing('new'),
    (item) => setEditing(item),
  );

  return (
    <RequirePermission permission="project_types.read">
      <Fragment>
        <Container width="fluid">
          <Toolbar>
            <ToolbarHeading>
              <ToolbarPageTitle />
              <ToolbarDescription>Categories your event templates are grouped under.</ToolbarDescription>
            </ToolbarHeading>
          </Toolbar>
        </Container>
        <Container width="fluid">
          <ResourceList key={nonce} config={config} />
        </Container>
        {editing && (
          <EventTypeDialog
            item={editing === 'new' ? null : editing}
            onClose={() => setEditing(null)}
            onSaved={() => {
              setEditing(null);
              setNonce((n) => n + 1);
            }}
          />
        )}
      </Fragment>
    </RequirePermission>
  );
}

function EventTypeDialog({
  item,
  onClose,
  onSaved,
}: {
  item: ProjectType | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { label } = useTerminology();
  const singular = label('project_type');
  const [name, setName] = useState(item?.name ?? '');
  const [description, setDescription] = useState(item?.description ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      if (item) {
        await emsService.updateType(item.id, { name, description });
      } else {
        await emsService.createType({ name, description });
      }
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
          <DialogTitle>
            {item ? `Edit ${singular.toLowerCase()}` : `New ${singular.toLowerCase()}`}
          </DialogTitle>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="et-name">Name *</Label>
            <Input id="et-name" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="et-desc">Description</Label>
            <Textarea
              id="et-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
            />
          </div>
          {error && <p className="text-destructive text-sm">{error}</p>}
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void save()} disabled={!name.trim() || busy}>
            {busy ? 'Saving…' : item ? 'Save' : 'Create'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
