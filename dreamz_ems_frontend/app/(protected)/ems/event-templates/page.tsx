'use client';

import { Fragment, useEffect, useState } from 'react';
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
import { Textarea } from '@/components/ui/textarea';
import { SearchSelect } from '@/components/platform/search-select';
import { useTerminology } from '@/hooks/use-terminology';
import { emsService } from '@/services/ems-service';
import type { ProjectType } from '@/types/ems';
import { useEventTemplatesListConfig, type TemplateRow } from './use-event-templates-list-config';

/** EMS Event Templates on the Resource shell — create / edit / delete the
 * presets events are spun up from. */
export default function EventTemplatesPage() {
  const router = useRouter();
  const [creating, setCreating] = useState(false);
  const [nonce, setNonce] = useState(0);
  const config = useEventTemplatesListConfig(
    () => setCreating(true),
    // Edit / row-click opens the detail page (Details + eligibility-flow editor).
    (item) => router.push(`/ems/event-templates/${item.id}`),
  );

  return (
    <RequirePermission permission="project_templates.read">
      <Fragment>
        <Container width="fluid">
          <Toolbar>
            <ToolbarHeading>
              <ToolbarPageTitle />
              <ToolbarDescription>Reusable presets your events are created from.</ToolbarDescription>
            </ToolbarHeading>
          </Toolbar>
        </Container>
        <Container width="fluid">
          <ResourceList key={nonce} config={config} />
        </Container>
        {creating && (
          <EventTemplateDialog
            item={null}
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

function EventTemplateDialog({
  item,
  onClose,
  onSaved,
}: {
  item: TemplateRow | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { label } = useTerminology();
  const singular = label('project_template');
  const typeLabel = label('project_type');
  const [types, setTypes] = useState<ProjectType[]>([]);
  const [typeId, setTypeId] = useState<string | null>(item?.typeId ?? null);
  const [name, setName] = useState(item?.name ?? '');
  const [description, setDescription] = useState(item?.description ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    emsService.listTypes({ pageSize: 200 }).then((r) => setTypes(r.items)).catch(() => setTypes([]));
  }, []);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      if (item) {
        await emsService.updateTemplate(item.id, { name, description });
      } else {
        if (!typeId) return;
        await emsService.createTemplate({ typeId, name, description });
      }
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save.');
      setBusy(false);
    }
  };

  const noTypes = !item && types.length === 0;

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>
            {item ? `Edit ${singular.toLowerCase()}` : `New ${singular.toLowerCase()}`}
          </DialogTitle>
        </DialogHeader>
        <DialogBody className="space-y-4">
          {noTypes ? (
            <p className="text-muted-foreground text-sm">
              Create a {typeLabel.toLowerCase()} first.
            </p>
          ) : (
            <>
              <div className="space-y-1.5">
                <Label>{typeLabel} *</Label>
                {item ? (
                  <Input value={item.typeName} disabled />
                ) : (
                  <SearchSelect
                    value={typeId}
                    onChange={setTypeId}
                    options={types.map((t) => ({ value: t.id, label: t.name }))}
                  />
                )}
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="tpl-name">Name *</Label>
                <Input id="tpl-name" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="tpl-desc">Description</Label>
                <Textarea
                  id="tpl-desc"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  rows={3}
                />
              </div>
            </>
          )}
          {error && <p className="text-destructive text-sm">{error}</p>}
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button
            onClick={() => void save()}
            disabled={noTypes || !name.trim() || (!item && !typeId) || busy}
          >
            {busy ? 'Saving…' : item ? 'Save' : 'Create'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
