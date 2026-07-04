'use client';

import { Fragment, useCallback, useEffect, useMemo, useState } from 'react';
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
import { SearchSelect } from '@/components/platform/search-select';
import { useStatusGraph } from '@/hooks/use-status-engine';
import { useTerminology } from '@/hooks/use-terminology';
import { emsService } from '@/services/ems-service';
import type { Project, ProjectTemplate } from '@/types/ems';
import { useEventsListConfig } from './use-events-list-config';

const PROJECT_ENTITY = 'project';

/** EMS Events on the Resource shell (search/sort/columns/select/export) — the
 * lifecycle status shows as a column and changes via the row/bulk "…". */
export default function EventsPage() {
  const router = useRouter();
  const engine = useStatusGraph(PROJECT_ENTITY);
  const [creating, setCreating] = useState(false);
  const [nonce, setNonce] = useState(0);

  const onCreate = useCallback(() => setCreating(true), []);
  const onEdit = useCallback((row: Project) => router.push(`/ems/events/${row.id}`), [router]);
  const ctx = useMemo(
    () => ({
      onCreate,
      onEdit,
      statuses: engine.graph?.statuses ?? [],
      transitions: engine.graph?.transitions ?? [],
    }),
    [onCreate, onEdit, engine.graph],
  );
  const config = useEventsListConfig(ctx);

  return (
    <RequirePermission permission="projects.read">
      <Fragment>
        <Container width="fluid">
          <Toolbar>
            <ToolbarHeading>
              <ToolbarPageTitle />
              <ToolbarDescription>Your events, created from reusable templates.</ToolbarDescription>
            </ToolbarHeading>
          </Toolbar>
        </Container>
        <Container width="fluid">
          <ResourceList key={nonce} config={config} />
        </Container>
        {creating && (
          <CreateEventDialog
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

function CreateEventDialog({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const { label } = useTerminology();
  const [templates, setTemplates] = useState<ProjectTemplate[]>([]);
  const [templateId, setTemplateId] = useState<string | null>(null);
  const [title, setTitle] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    emsService.listTemplates().then((r) => setTemplates(r.items)).catch(() => setTemplates([]));
  }, []);

  const save = async () => {
    if (!templateId) return;
    setBusy(true);
    setError(null);
    try {
      await emsService.createProject({ templateId, title });
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
          <DialogTitle>New {label('project').toLowerCase()}</DialogTitle>
        </DialogHeader>
        <DialogBody className="space-y-4">
          {templates.length === 0 ? (
            <p className="text-muted-foreground text-sm">
              Create an {label('project_template').toLowerCase()} first.
            </p>
          ) : (
            <>
              <div className="space-y-1.5">
                <Label>{label('project_template')} *</Label>
                <SearchSelect
                  value={templateId}
                  onChange={setTemplateId}
                  options={templates.map((t) => ({ value: t.id, label: t.name }))}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="ev-title">Title *</Label>
                <Input id="ev-title" value={title} onChange={(e) => setTitle(e.target.value)} autoFocus />
              </div>
            </>
          )}
          {error && <p className="text-destructive text-sm">{error}</p>}
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={() => void save()} disabled={!templateId || !title || busy}>
            {busy ? 'Saving…' : 'Create'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
