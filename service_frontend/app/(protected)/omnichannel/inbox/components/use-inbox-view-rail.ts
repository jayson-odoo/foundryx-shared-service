'use client';

/**
 * The inbox view rail's state and actions (plan 27, AC-IVE-20/22/24; plan 28
 * Team Inbox), shared by both looks of `inbox-view-rail.tsx` so they cannot
 * drift: the rail entries, the selection, the save/rename dialog state and
 * the deferred (grace-window) delete of a saved view.
 */
import { useMemo, useRef, useState } from 'react';
import { useSession } from 'next-auth/react';
import type { InboxView } from '@/types/omnichannel';
import { deferredDoneMessage, presentContinuous } from '@/lib/deferred-verb';
import { toast } from '@/lib/toast';
import { useCan } from '@/hooks/use-can';
import type { ConversationFilters } from '@/hooks/use-conversations';
import { useDeferredAction } from '@/hooks/use-deferred-action';
import { useInboxViews } from '@/hooks/use-inbox-views';
import { useMyTeams } from '@/hooks/use-my-teams';
import { useStatusGraph } from '@/hooks/use-status-engine';
import { useTeams } from '@/hooks/use-teams';
import {
  deferredToast,
  dismissDeferredToast,
} from '@/components/platform/resource-actions/deferred-toast';
import { CONTACT_LIFECYCLE_ENTITY } from '../../settings/workspaces/components/workspace-lifecycle-tab';
import {
  buildRailEntries,
  type InboxRailEntry,
  type RailStage,
} from './inbox-rail-entries';
import { useInboxRailSelection } from './use-inbox-rail-selection';

export function entryToOption(entry: InboxRailEntry) {
  return {
    label:
      entry.kind === 'view' && entry.isShared
        ? `${entry.label} (shared)`
        : entry.label,
    value: entry.key,
  };
}

export function useInboxViewRail(
  workspaceId: string | null,
  filters: ConversationFilters,
  setFilters: (patch: Partial<ConversationFilters>) => void,
) {
  const { can } = useCan();
  const { data: session } = useSession();
  const currentUserId = session?.user?.id ?? null;
  const canManageShared = can('inbox_views.manage');
  // `GET /teams` is gated `teams.read` server-side - the "All teams" group
  // (browsing every team in the tenant, not just the caller's own) can only
  // ever show for a caller who actually holds that permission (review round
  // 1, finding 4/5/6). An agent with only `conversations.assign` still sees
  // their OWN teams via `useMyTeams()` (no `teams.read` required there).
  const canBrowseAllTeams = can('teams.read');
  // Scoped machine - never fire before the workspace id (its scope) resolves,
  // or the backend 422s "Workspace is required for this entity" on mount.
  const lifecycleGraph = useStatusGraph(
    workspaceId ? CONTACT_LIFECYCLE_ENTITY : null,
    workspaceId ?? undefined,
  );
  const { views, create, update, refresh } = useInboxViews(workspaceId);
  const { teams: myTeams } = useMyTeams();
  // Never call `GET /teams` for a caller without `teams.read` - it would 403.
  const { teams: allTeams } = useTeams({ enabled: canBrowseAllTeams });

  const stages = useMemo<RailStage[]>(
    () =>
      [...(lifecycleGraph.graph?.statuses ?? [])]
        .sort((a, b) => a.sortOrder - b.sortOrder)
        .map((s) => ({ id: s.id, label: s.label, color: s.color })),
    [lifecycleGraph.graph],
  );
  const otherTeams = useMemo(() => {
    if (!canBrowseAllTeams) return [];
    const mine = new Set(myTeams.map((t) => t.id));
    return allTeams.filter((t) => !mine.has(t.id));
  }, [canBrowseAllTeams, myTeams, allTeams]);
  const entries = useMemo(
    () => buildRailEntries(stages, views, { mine: myTeams, other: otherTeams }),
    [stages, views, myTeams, otherTeams],
  );
  const { selectedKey, select } = useInboxRailSelection(
    filters,
    setFilters,
    stages,
    views,
    workspaceId,
  );

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingView, setEditingView] = useState<InboxView | null>(null);

  const activeDeleteToastRef = useRef<{
    id: string | number;
    name: string;
    viewId: string;
  } | null>(null);
  const settleActiveDelete = () => {
    const active = activeDeleteToastRef.current;
    if (active) dismissDeferredToast(active.id);
    activeDeleteToastRef.current = null;
    return active;
  };
  const deferred = useDeferredAction({
    onCommitted: () => {
      const active = settleActiveDelete();
      toast.success(
        active ? deferredDoneMessage('Delete', 'inbox_view', 1) : 'Done.',
      );
      // Review round 2 (finding 2): the just-deleted view may still be the
      // selected rail entry - the next thread-list fetch would 404 "View not
      // found" against a viewId that no longer exists. Fall back to All
      // exactly like clicking the All rail entry (same filter patch + URL
      // key), never leave `filters.viewId` pointing at a deleted row.
      if (active && filters.viewId === active.viewId) {
        select({ kind: 'default', key: 'all', label: 'All' });
      }
      void refresh();
    },
    onFailed: (error) => {
      settleActiveDelete();
      toast.error(error || 'The action failed.');
    },
    onCancelledElsewhere: () => settleActiveDelete(),
  });

  const deleteView = async (view: InboxView) => {
    // Round-3 codex triage F3 (supersedes review round 2, finding 3): ONE
    // `useDeferredAction` instance serves every row - `start()` OVERWRITES
    // `parkedRef` wholesale, so a settle-then-overwrite here would silently
    // stop polling/refreshing/toasting for the FIRST delete the instant a
    // SECOND one starts (its server-side action still resolves, but this
    // component never learns it did, so the rail never auto-refreshes it
    // away). Refuse a second delete while one is still counting down instead
    // - the safest option (no change to the shared engine hook's contract,
    // and the first delete keeps its full toast/poll/fallback intact).
    const active = activeDeleteToastRef.current;
    if (active) {
      if (active.viewId === view.id) return; // already parked - a double click is a no-op
      toast.error(`Finish deleting "${active.name}" first.`);
      return;
    }
    const toastId = `pending-action-inbox-view-${view.id}`;
    try {
      const { commitAt, windowSeconds, parkedEntityIds } = await deferred.start(
        'inbox_views.delete',
        {
          entityType: 'inbox_view',
          entityId: view.id,
        },
      );
      if (parkedEntityIds.length === 0) return;
      activeDeleteToastRef.current = {
        id: toastId,
        name: view.name,
        viewId: view.id,
      };
      deferredToast({
        id: toastId,
        verb: presentContinuous('Delete'),
        commitAt,
        windowSeconds,
        onCancel: () => {
          void deferred.cancel();
          activeDeleteToastRef.current = null;
          dismissDeferredToast(toastId);
        },
      });
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : 'Could not start that action.',
      );
    }
  };

  // AC-IVE-22 - saving adds the view to the rail AND selects it. `views` in
  // this closure may still be one render behind the just-created row (create()
  // awaits its own refresh, but this component hasn't re-rendered with it
  // yet), so select from the CREATED row directly rather than re-looking it
  // up - `select`'s fallback path (view not found in `views`) already just
  // sets `viewId`, which is correct here since the filter fields already
  // match `currentFilter` (that's what was just saved).
  const selectCreatedView = (created: InboxView) =>
    select({
      kind: 'view',
      key: created.id,
      viewId: created.id,
      label: created.name,
      isShared: created.isShared,
    });

  const openCreate = () => {
    setEditingView(null);
    setDialogOpen(true);
  };
  const openEdit = (view: InboxView) => {
    setEditingView(view);
    setDialogOpen(true);
  };

  const currentFilter = useMemo(
    () => ({
      assignee: filters.assignee,
      statuses: filters.status === 'ALL' ? undefined : [filters.status],
      priority: filters.priority,
      lifecycleStageIds: filters.lifecycleStageIds,
      tagIds: filters.tagIds,
      channelIds: filters.channelIds,
      unreplied: filters.unreplied,
      sort: filters.sort,
      // AC-TEM-46 - a saved view captures the rail's currently-selected team
      // scope (if any), so re-selecting the view restores it too.
      teamIds: filters.teamId ? [filters.teamId] : undefined,
    }),
    [filters],
  );

  return {
    entries,
    stages,
    myTeams,
    otherTeams,
    views,
    selectedKey,
    select,
    currentUserId,
    canManageShared,
    dialogOpen,
    setDialogOpen,
    editingView,
    openCreate,
    openEdit,
    deleteView,
    selectCreatedView,
    create,
    update,
    currentFilter,
  };
}

export type UseInboxViewRailResult = ReturnType<typeof useInboxViewRail>;
