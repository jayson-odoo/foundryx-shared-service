'use client';

/**
 * Inbox view rail (plan 27, AC-IVE-20/22/24) - All / Mine / Unassigned, one
 * entry per lifecycle stage (real workspace graph, `statuses.read`), then
 * saved views (own + shared, mock in S0). ONE component, two renderings via
 * `variant` (never fork a parallel component, per the reuse mandate):
 * `sidebar` (>=1024px, a vertical nav column) and `select` (below 1024px, a
 * single `SearchSelect` collapsing the same options - AC-IVE-24).
 *
 * Delete is a deferred (grace-window) action (review round 1 frontend
 * follow-up, finding 5) - no confirm dialog; `useDeferredAction` parks the
 * registered `inbox_views.delete` handler and a `deferredToast` (the same
 * countdown the Resource shell's row actions use) replaces it while it
 * counts down.
 */
import { useMemo, useRef, useState } from 'react';
import { useSession } from 'next-auth/react';
import { MoreHorizontal, Plus } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { deferredToast, dismissDeferredToast } from '@/components/platform/resource-actions/deferred-toast';
import { SearchSelect, type SearchSelectGroup } from '@/components/platform/search-select';
import { useCan } from '@/hooks/use-can';
import { useDeferredAction } from '@/hooks/use-deferred-action';
import type { ConversationFilters } from '@/hooks/use-conversations';
import { useInboxViews } from '@/hooks/use-inbox-views';
import { useStatusGraph } from '@/hooks/use-status-engine';
import { deferredDoneMessage, presentContinuous } from '@/lib/deferred-verb';
import { toast } from '@/lib/toast';
import { cn } from '@/lib/utils';
import type { InboxView } from '@/types/omnichannel';

import { CONTACT_LIFECYCLE_ENTITY } from '../../settings/workspaces/components/workspace-lifecycle-tab';
import { buildRailEntries, type InboxRailEntry, type RailStage } from './inbox-rail-entries';
import { InboxViewDialog } from './inbox-view-dialog';
import { useInboxRailSelection } from './use-inbox-rail-selection';

export interface InboxViewRailProps {
  workspaceId: string | null;
  filters: ConversationFilters;
  setFilters: (patch: Partial<ConversationFilters>) => void;
  variant?: 'sidebar' | 'select';
  className?: string;
}

function entryToOption(entry: InboxRailEntry) {
  return { label: entry.kind === 'view' && entry.isShared ? `${entry.label} (shared)` : entry.label, value: entry.key };
}

export function InboxViewRail({ workspaceId, filters, setFilters, variant = 'sidebar', className }: InboxViewRailProps) {
  const { can } = useCan();
  const { data: session } = useSession();
  const currentUserId = session?.user?.id ?? null;
  const canManageShared = can('inbox_views.manage');
  // Scoped machine - never fire before the workspace id (its scope) resolves,
  // or the backend 422s "Workspace is required for this entity" on mount.
  const lifecycleGraph = useStatusGraph(workspaceId ? CONTACT_LIFECYCLE_ENTITY : null, workspaceId ?? undefined);
  const { views, create, update, refresh } = useInboxViews(workspaceId);

  const stages = useMemo<RailStage[]>(
    () =>
      [...(lifecycleGraph.graph?.statuses ?? [])]
        .sort((a, b) => a.sortOrder - b.sortOrder)
        .map((s) => ({ id: s.id, label: s.label, color: s.color })),
    [lifecycleGraph.graph],
  );
  const entries = useMemo(() => buildRailEntries(stages, views), [stages, views]);
  const { selectedKey, select } = useInboxRailSelection(filters, setFilters, stages, views);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingView, setEditingView] = useState<InboxView | null>(null);

  const activeDeleteToastRef = useRef<{ id: string | number; name: string; viewId: string } | null>(null);
  const settleActiveDelete = () => {
    const active = activeDeleteToastRef.current;
    if (active) dismissDeferredToast(active.id);
    activeDeleteToastRef.current = null;
    return active;
  };
  const deferred = useDeferredAction({
    onCommitted: () => {
      const active = settleActiveDelete();
      toast.success(active ? deferredDoneMessage('Delete', 'inbox_view', 1) : 'Done.');
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
    // Review round 2 (finding 3): ONE `useDeferredAction` instance serves
    // every row - `start()` overwrites `parkedRef`, so deleting view A then
    // view B inside the grace window would leave A's toast live with an
    // `onCancel` that (after the overwrite) actually cancels B. Settle any
    // already-active delete's TOAST before starting the next one (matches
    // the engine's one-visible-countdown model) - A's own pending action
    // still resolves server-side on its own countdown, it is just no longer
    // the one this toast/hook instance is tracking.
    settleActiveDelete();
    const toastId = `pending-action-inbox-view-${view.id}`;
    try {
      const { commitAt, windowSeconds, parkedEntityIds } = await deferred.start('inbox_views.delete', {
        entityType: 'inbox_view',
        entityId: view.id,
      });
      if (parkedEntityIds.length === 0) return;
      activeDeleteToastRef.current = { id: toastId, name: view.name, viewId: view.id };
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
      toast.error(error instanceof Error ? error.message : 'Could not start that action.');
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
    select({ kind: 'view', key: created.id, viewId: created.id, label: created.name, isShared: created.isShared });

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
    }),
    [filters],
  );

  if (variant === 'select') {
    const groups: SearchSelectGroup[] = [
      { label: 'Inbox', options: entries.filter((e) => e.kind === 'default').map(entryToOption) },
      { label: 'Lifecycle', options: entries.filter((e) => e.kind === 'lifecycle').map(entryToOption) },
      ...(entries.some((e) => e.kind === 'view')
        ? [{ label: 'Views', options: entries.filter((e) => e.kind === 'view').map(entryToOption) }]
        : []),
    ];
    return (
      <div className={cn('flex items-center gap-2', className)} data-testid="inbox-view-select">
        <SearchSelect
          groups={groups}
          value={selectedKey}
          onChange={(key) => {
            const entry = entries.find((e) => e.key === key);
            if (entry) select(entry);
          }}
          ariaLabel="View"
          className="flex-1"
        />
        <Button variant="outline" size="icon" aria-label="Save view" onClick={openCreate}>
          <Plus className="size-4" />
        </Button>
        <InboxViewDialog
          open={dialogOpen}
          onOpenChange={setDialogOpen}
          view={editingView}
          canShare={canManageShared}
          onCreate={async (values) => selectCreatedView(await create({ ...values, filter: currentFilter }))}
          onUpdate={(id, values) => update(id, values)}
        />
      </div>
    );
  }

  return (
    <div className={cn('flex h-full flex-col gap-4 overflow-y-auto p-2', className)} data-testid="inbox-view-rail">
      <nav className="flex flex-col gap-0.5">
        {entries
          .filter((e) => e.kind === 'default')
          .map((e) => (
            <button
              key={e.key}
              type="button"
              onClick={() => select(e)}
              className={cn(
                PRESSED_CLASS,
                'flex items-center rounded-md px-2.5 py-1.5 text-start text-sm font-medium transition-colors hover:bg-accent',
                selectedKey === e.key && 'bg-accent text-accent-foreground',
              )}
              data-testid={`rail-${e.key}`}
            >
              {e.label}
            </button>
          ))}
      </nav>

      {stages.length > 0 && (
        <div>
          <p className="mb-1 px-2.5 text-xs font-semibold text-muted-foreground uppercase">Lifecycle</p>
          <nav className="flex flex-col gap-0.5">
            {entries
              .filter((e) => e.kind === 'lifecycle')
              .map((e) => (
                <button
                  key={e.key}
                  type="button"
                  onClick={() => select(e)}
                  className={cn(
                    PRESSED_CLASS,
                    'flex items-center gap-2 rounded-md px-2.5 py-1.5 text-start text-sm transition-colors hover:bg-accent',
                    selectedKey === e.key && 'bg-accent font-medium text-accent-foreground',
                  )}
                  data-testid={`rail-${e.key}`}
                >
                  <span className="truncate">{e.label}</span>
                </button>
              ))}
          </nav>
        </div>
      )}

      <div>
        <div className="mb-1 flex items-center justify-between px-2.5">
          <p className="text-xs font-semibold text-muted-foreground uppercase">Views</p>
          <Button variant="ghost" size="icon" className="size-6" aria-label="Save view" onClick={openCreate} data-testid="save-view-trigger">
            <Plus className="size-3.5" />
          </Button>
        </div>
        <nav className="flex flex-col gap-0.5">
          {entries
            .filter((e): e is Extract<InboxRailEntry, { kind: 'view' }> => e.kind === 'view')
            .map((e) => {
              const view = views.find((v) => v.id === e.viewId);
              // D-A3-11: the owner may always manage their own view; a SHARED
              // view or someone else's additionally needs `inbox_views.manage`
              // (the server enforces this too - this only hides the control).
              const mayManage = view
                ? (currentUserId !== null && view.ownerUserId === currentUserId) || canManageShared
                : false;
              return (
                <div
                  key={e.key}
                  className={cn(
                    'group flex items-center gap-1 rounded-md px-1 py-0.5 hover:bg-accent',
                    selectedKey === e.key && 'bg-accent',
                  )}
                >
                  <button
                    type="button"
                    onClick={() => select(e)}
                    className={cn(PRESSED_CLASS, 'min-w-0 flex-1 truncate rounded-md px-1.5 py-1 text-start text-sm')}
                    data-testid={`rail-view-${e.viewId}`}
                  >
                    {e.label}
                    {e.isShared && <span className="ms-1.5 text-xs text-muted-foreground">(shared)</span>}
                  </button>
                  {mayManage && (
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="size-6 shrink-0 opacity-0 group-hover:opacity-100"
                          aria-label={`Manage view ${e.label}`}
                          data-testid={`rail-view-menu-${e.viewId}`}
                        >
                          <MoreHorizontal className="size-3.5" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem onClick={() => view && openEdit(view)}>Rename</DropdownMenuItem>
                        <DropdownMenuItem
                          className="text-destructive"
                          onClick={() => view && void deleteView(view)}
                        >
                          Delete
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  )}
                </div>
              );
            })}
        </nav>
      </div>

      <InboxViewDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        view={editingView}
        canShare={canManageShared}
        onCreate={async (values) => selectCreatedView(await create({ ...values, filter: currentFilter }))}
        onUpdate={(id, values) => update(id, values)}
      />
    </div>
  );
}
