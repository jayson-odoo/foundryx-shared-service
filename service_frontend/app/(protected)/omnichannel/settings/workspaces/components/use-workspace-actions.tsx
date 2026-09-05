'use client';

import { useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { Pencil, RotateCcw, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import type { ResourceAction } from '@/components/platform/resource-list';
import { workspaceService } from '@/services/workspace-service';
import type { Workspace } from '@/types/omnichannel';
import { workspaceFormHref } from './paths';

/** The Workspace action registry (plan 04 §7). The default workspace can't be trashed. */
export function useWorkspaceActions(): ResourceAction<Workspace>[] {
  const router = useRouter();

  return useMemo<ResourceAction<Workspace>[]>(() => {
    const ids = (rows: Workspace[]) => rows.map((r) => r.id);

    return [
      {
        id: 'edit',
        label: 'Edit',
        icon: Pencil,
        permission: 'workspaces.manage',
        surfaces: { row: true },
        run: ([ws], rt) => {
          if (!ws) return;
          router.push(workspaceFormHref(ws.id, { ctx: rt.ctx, index: rt.index, edit: true }));
        },
      },
      {
        id: 'trash',
        label: 'Trash',
        icon: Trash2,
        tone: 'destructive',
        permission: 'workspaces.manage',
        surfaces: { row: true, bulk: true, form: true },
        isVisible: (rows) => rows.length > 0 && rows.every((r) => !r.isDefault && !r.isTrashed),
        // Grace-window deferred action (sprint-4/23, T5 fix round 1, item
        // 15) - no confirm, no `run` (the registered `workspaces.trash`
        // handler commits it server-side).
        deferred: { actionKey: 'workspaces.trash', entityType: 'workspace' },
      },
      {
        id: 'restore',
        label: 'Restore',
        icon: RotateCcw,
        permission: 'workspaces.manage',
        surfaces: { row: true, bulk: true },
        isVisible: (rows) => rows.length > 0 && rows.every((r) => r.isTrashed),
        run: async (rows, rt) => {
          await workspaceService.restore(ids(rows));
          toast.success(`Restored ${rows.length} workspace(s).`);
          rt.reload();
        },
      },
    ];
  }, [router]);
}
