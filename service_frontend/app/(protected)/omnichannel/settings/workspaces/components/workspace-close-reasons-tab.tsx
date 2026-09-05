'use client';

/**
 * Close reasons tab (plan 27, AC-IVE-31) - the workspace's close-reason
 * registry as an embedded ResourceList, after Tags, hidden while creating.
 * Clones `workspace-tags-tab.tsx` exactly. Read-only (no create/edit/delete)
 * without `close_reasons.manage` - `useCloseReasonList` already omits the
 * create action; the row menu's own permission gate hides edit/delete/
 * deactivate for the same caller (foolproof-UI, backend is the real gate).
 *
 * Delete is a deferred (grace-window) action (review round 1 frontend
 * follow-up, finding 5) - `useCloseReasonList` wires it through the shell's
 * own `ActionMenu`/`useDeferredAction`, so there is no hand-rolled confirm
 * dialog here; `onChanged` just re-pulls `reasons` after a commit.
 */
import { useCallback, useState } from 'react';
import { Info } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { ResourceList } from '@/components/platform/resource-list';
import { useCan } from '@/hooks/use-can';
import { useCloseReasons } from '@/hooks/use-close-reasons';
import type { CloseReason } from '@/types/omnichannel';
import { CloseReasonDialog } from './close-reason-dialog';
import { useCloseReasonList } from './use-close-reason-list';

export function WorkspaceCloseReasonsTab({ workspaceId, creating }: { workspaceId: string | null; creating: boolean }) {
  const { can } = useCan();
  const canManage = can('close_reasons.manage');
  const { reasons, create, update, refresh } = useCloseReasons(workspaceId);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingReason, setEditingReason] = useState<CloseReason | null>(null);

  const onAdd = useCallback(() => {
    setEditingReason(null);
    setDialogOpen(true);
  }, []);
  const onEdit = useCallback((reason: CloseReason) => {
    setEditingReason(reason);
    setDialogOpen(true);
  }, []);
  const onSetActive = useCallback(
    (reason: CloseReason, isActive: boolean) => void update(reason.id, { isActive }),
    [update],
  );

  const { config } = useCloseReasonList({
    reasons,
    canManage,
    onEdit,
    onSetActive,
    onAdd,
    onChanged: refresh,
  });

  if (creating || !workspaceId) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center gap-2 py-16 text-center">
          <Info className="size-8 text-muted-foreground" />
          <p className="text-sm font-medium">Save the workspace to manage close reasons.</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <ResourceList config={config} />
      <CloseReasonDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        reason={editingReason}
        nextSortOrder={reasons.length}
        onCreate={(values) => create(values)}
        onUpdate={(id, values) => update(id, values)}
      />
    </div>
  );
}
