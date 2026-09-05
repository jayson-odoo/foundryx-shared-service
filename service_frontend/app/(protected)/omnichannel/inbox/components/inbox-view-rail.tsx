'use client';

/**
 * Inbox view rail (plan 27, AC-IVE-20/22/24) - All / Mine / Unassigned, one
 * entry per lifecycle stage (real workspace graph, `statuses.read`), then
 * saved views (own + shared, mock in S0). ONE component, two renderings via
 * `variant` (never fork a parallel component, per the reuse mandate):
 * `sidebar` (>=1024px, a vertical nav column) and `select` (below 1024px, a
 * single `SearchSelect` collapsing the same options - AC-IVE-24).
 */
import { useMemo, useState } from 'react';
import { MoreHorizontal, Plus } from 'lucide-react';

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
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { SearchSelect, type SearchSelectGroup } from '@/components/platform/search-select';
import { useCan } from '@/hooks/use-can';
import type { ConversationFilters } from '@/hooks/use-conversations';
import { useInboxViews } from '@/hooks/use-inbox-views';
import { useStatusGraph } from '@/hooks/use-status-engine';
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
  const canManageShared = can('inbox_views.manage');
  // Scoped machine - never fire before the workspace id (its scope) resolves,
  // or the backend 422s "Workspace is required for this entity" on mount.
  const lifecycleGraph = useStatusGraph(workspaceId ? CONTACT_LIFECYCLE_ENTITY : null, workspaceId ?? undefined);
  const { views, create, update, remove } = useInboxViews(workspaceId);

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
  const [pendingDelete, setPendingDelete] = useState<InboxView | null>(null);

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
              // S0 MOCK convention: `inbox-view-service.mock.ts` stamps every
              // created/seeded "own" view with the literal 'usr-demo' (mirrors
              // `MOCK_CURRENT_USER` in conversation-service.mock.ts) rather
              // than the real session user id - S4 wires this to the real
              // `ownerUserId` returned by the backend (D-A3-11).
              const mayManage = view ? view.ownerUserId === 'usr-demo' || canManageShared : false;
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
                    className="min-w-0 flex-1 truncate rounded-md px-1.5 py-1 text-start text-sm"
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
                          onClick={() => view && setPendingDelete(view)}
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
              onClick={() => {
                if (pendingDelete) void remove(pendingDelete.id);
                setPendingDelete(null);
              }}
            >
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
