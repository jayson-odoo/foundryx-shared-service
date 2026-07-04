'use client';

import { useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { Pencil, Trash2 } from 'lucide-react';
import { toast } from 'sonner';
import type { ResourceAction } from '@/components/platform/resource-list';
import { roleService } from '@/services/role-service';
import type { RoleListItem } from '@/types/role';
import { roleFormHref, rolesListPath } from './paths';

/**
 * The Role action registry (plan 03 §7.5). Edit (row) + Delete (row/form). Delete
 * is hidden for system roles (`isSystem`) and confirmed via dialog; on success it
 * refreshes the list (row surface) and returns to the list (form surface).
 */
export function useRoleActions(): ResourceAction<RoleListItem>[] {
  const router = useRouter();

  return useMemo<ResourceAction<RoleListItem>[]>(() => {
    return [
      {
        id: 'edit',
        label: 'Edit',
        icon: Pencil,
        permission: 'roles.update',
        surfaces: { row: true },
        run: ([role], rt) => {
          if (!role) return;
          router.push(roleFormHref(role.id, { ctx: rt.ctx, index: rt.index, edit: true }));
        },
      },
      {
        id: 'delete',
        label: 'Delete role',
        icon: Trash2,
        tone: 'destructive',
        permission: 'roles.delete',
        surfaces: { row: true, bulk: true, form: true },
        // Hidden entirely when any selected row is a system role.
        isVisible: (rows) => rows.length > 0 && rows.every((r) => !r.isSystem),
        confirm: {
          title: 'Delete this role?',
          description:
            'Users currently assigned to it will have their role unset. This action cannot be undone.',
          confirmLabel: 'Delete role',
        },
        run: async (rows, rt) => {
          await Promise.all(rows.map((r) => roleService.remove(r.id)));
          toast.success(`Deleted ${rows.length} role(s).`);
          rt.reload();
          router.push(rolesListPath);
        },
      },
    ];
  }, [router]);
}
