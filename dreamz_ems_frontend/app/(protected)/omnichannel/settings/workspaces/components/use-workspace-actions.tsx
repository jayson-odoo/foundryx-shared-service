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
        confirm: {
          title: 'Move to trash?',
          description:
            'The selected workspace(s) will be moved to the trash. Channels and contacts in them become inaccessible until restored.',
          confirmLabel: 'Trash',
        },
        run: async (rows, rt) => {
          await workspaceService.trash(ids(rows));
          toast.success(`Moved ${rows.length} workspace(s) to trash.`);
          rt.reload();
        },
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
