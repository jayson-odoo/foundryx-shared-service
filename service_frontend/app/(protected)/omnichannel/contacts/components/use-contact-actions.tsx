'use client';

import { useMemo } from 'react';
import { Tag, TagIcon, UserPlus2, Workflow } from 'lucide-react';
import type { ResourceAction } from '@/components/platform/resource-list';
import type { ContactListItem } from '@/types/omnichannel';

/**
 * The Contact action registry (D-A2-5) - Assign / Add tags / Remove tags /
 * Move lifecycle, surfaced in the row "…" menu AND the bulk toolbar. Each
 * action only OPENS the matching dialog (owned by the list page, which also
 * holds the workspace-scoped picker data) - the actual mutation runs through
 * `use-contact-bulk.ts` once the dialog is confirmed, then calls the SAME
 * `reload` the shell would have passed a self-contained action (keeps the
 * list's search/filter/sort/page state instead of a full remount). Delete /
 * merge / block are NOT in this slice (D-A2-15).
 */
export interface ContactActionCallbacks {
  onBulkAssign: (rows: ContactListItem[], reload: () => void) => void;
  onAddTags: (rows: ContactListItem[], reload: () => void) => void;
  onRemoveTags: (rows: ContactListItem[], reload: () => void) => void;
  onMoveLifecycle: (rows: ContactListItem[], reload: () => void) => void;
}

export function useContactActions(callbacks: ContactActionCallbacks): ResourceAction<ContactListItem>[] {
  return useMemo<ResourceAction<ContactListItem>[]>(
    () => [
      {
        id: 'bulk-assign',
        label: 'Assign',
        icon: UserPlus2,
        permission: 'contacts.manage',
        surfaces: { row: true, bulk: true },
        run: (rows, rt) => callbacks.onBulkAssign(rows, rt.reload),
      },
      {
        id: 'add-tags',
        label: 'Add tags',
        icon: Tag,
        permission: 'contacts.manage',
        surfaces: { row: true, bulk: true },
        run: (rows, rt) => callbacks.onAddTags(rows, rt.reload),
      },
      {
        id: 'remove-tags',
        label: 'Remove tags',
        icon: TagIcon,
        permission: 'contacts.manage',
        surfaces: { row: true, bulk: true },
        isVisible: (rows) => rows.some((r) => r.tags.length > 0),
        run: (rows, rt) => callbacks.onRemoveTags(rows, rt.reload),
      },
      {
        id: 'move-lifecycle',
        label: 'Move lifecycle',
        icon: Workflow,
        permission: 'contacts.manage',
        surfaces: { row: true, bulk: true },
        run: (rows, rt) => callbacks.onMoveLifecycle(rows, rt.reload),
      },
    ],
    [callbacks],
  );
}
