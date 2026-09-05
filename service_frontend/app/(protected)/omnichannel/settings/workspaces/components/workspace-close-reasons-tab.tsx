'use client';

/**
 * Close reasons tab (plan 27, AC-IVE-31) - the workspace's close-reason
 * registry as an embedded ResourceList, after Tags, hidden while creating.
 * Clones `workspace-tags-tab.tsx` exactly. Read-only (no create/edit/delete)
 * without `close_reasons.manage` - `useCloseReasonList` already omits the
 * create action; the row menu's own permission gate hides edit/delete/
 * deactivate for the same caller (foolproof-UI, backend is the real gate).
 */
import { useCallback, useState } from 'react';
import { Info } from 'lucide-react';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
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
  const { reasons, create, update, remove } = useCloseReasons(workspaceId);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingReason, setEditingReason] = useState<CloseReason | null>(null);
  const [pendingDelete, setPendingDelete] = useState<CloseReason | null>(null);

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
    onDelete: setPendingDelete,
    onSetActive,
    onAdd,
  });

  const confirmDelete = () => {
    if (pendingDelete) void remove(pendingDelete.id);
  };

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
      <AlertDialog open={!!pendingDelete} onOpenChange={(open) => !open && setPendingDelete(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete &ldquo;{pendingDelete?.name}&rdquo;?</AlertDialogTitle>
            <AlertDialogDescription>This cannot be undone.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
              onClick={confirmDelete}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
