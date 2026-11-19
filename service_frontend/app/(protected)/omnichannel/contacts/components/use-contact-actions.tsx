'use client';

import { useCallback, useMemo } from 'react';
import { createLucideIcon, Tag, TagIcon, UserPlus2, Workflow } from 'lucide-react';
import type { ResourceAction, ResourceActionRuntime } from '@/components/platform/resource-list';
import { useFx } from '@/hooks/use-fx';
import type { ContactListItem } from '@/types/omnichannel';
import { useContactEraseAction } from './use-contact-erase-action';

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
/**
 * Foundryx UIUX switch only: "one icon per meaning" (playbook "Other Actions
 * are icon buttons"), so Remove tags gets a tag with a minus instead of the
 * same tag Add tags shows. The switch-off menus keep their icons.
 */
export const TagMinusIcon = createLucideIcon('tag-minus', [
  ['path', { d: 'M12.586 2.586A2 2 0 0 0 11.172 2H4a2 2 0 0 0-2 2v7.172a2 2 0 0 0 .586 1.414l6.5 6.5', key: 'fxtagm1' }],
  ['path', { d: 'M12.586 2.586l6.828 6.828a2 2 0 0 1 0 2.828L17 14.657', key: 'fxtagm2' }],
  ['circle', { cx: '7.5', cy: '7.5', r: '.5', fill: 'currentColor', key: 'fxtagm3' }],
  ['path', { d: 'M15 19h7', key: 'fxtagm4' }],
]);

export interface ContactActionCallbacks {
  onBulkAssign: (rows: ContactListItem[], reload: () => void) => void;
  onAddTags: (rows: ContactListItem[], reload: () => void) => void;
  onRemoveTags: (rows: ContactListItem[], reload: () => void) => void;
  onMoveLifecycle: (rows: ContactListItem[], reload: () => void) => void;
}

export function useContactActions(callbacks: ContactActionCallbacks): ResourceAction<ContactListItem>[] {
  // Depend on the INDIVIDUAL callbacks, not the `callbacks` object itself
  // (finding 7, review round 1) - the caller passes a fresh object literal
  // every render, so a dependency on `callbacks` recomputed this array (and
  // therefore `config`/`config.fetcher` downstream) on every render, and
  // `useResourceList`'s fetch effect keys off `fetcher` identity - one
  // extra network fetch per render. The caller now memoizes each callback
  // with `useCallback`, so THESE deps are actually stable.
  const { onBulkAssign, onAddTags, onRemoveTags, onMoveLifecycle } = callbacks;
  const fx = useFx();
  const reloadAfterErase = useCallback((runtime: ResourceActionRuntime) => runtime.reload(), []);
  const eraseAction = useContactEraseAction('row', reloadAfterErase);
  return useMemo<ResourceAction<ContactListItem>[]>(
    () => [
      {
        id: 'bulk-assign',
        label: 'Assign',
        icon: UserPlus2,
        permission: 'contacts.manage',
        surfaces: { row: true, bulk: true },
        run: (rows, rt) => onBulkAssign(rows, rt.reload),
      },
      {
        id: 'add-tags',
        label: 'Add tags',
        icon: Tag,
        permission: 'contacts.manage',
        surfaces: { row: true, bulk: true },
        run: (rows, rt) => onAddTags(rows, rt.reload),
      },
      {
        id: 'remove-tags',
        label: 'Remove tags',
        icon: fx ? TagMinusIcon : TagIcon,
        permission: 'contacts.manage',
        surfaces: { row: true, bulk: true },
        isVisible: (rows) => rows.some((r) => r.tags.length > 0),
        run: (rows, rt) => onRemoveTags(rows, rt.reload),
      },
      {
        id: 'move-lifecycle',
        label: 'Move lifecycle',
        icon: Workflow,
        permission: 'contacts.manage',
        surfaces: { row: true, bulk: true },
        run: (rows, rt) => onMoveLifecycle(rows, rt.reload),
      },
      eraseAction,
    ],
    [onBulkAssign, onAddTags, onRemoveTags, onMoveLifecycle, eraseAction, fx],
  );
}
