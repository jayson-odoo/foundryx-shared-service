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
 *
 * Plan 28 (roadmap A8, D-A8-4) folds Team Inbox into this SAME rail as a
 * third section (My teams, each with a nested Unassigned row, plus an "All
 * teams" group for `conversations.assign` holders) rather than a parallel
 * `TeamRail` component living beside it - one rail, one selection model.
 */
import { MoreHorizontal, Plus } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { SearchSelect, type SearchSelectGroup } from '@/components/platform/search-select';
import type { ConversationFilters } from '@/hooks/use-conversations';
import { useFx } from '@/hooks/use-fx';
import { cn } from '@/lib/utils';

import { FxInboxViewRail } from './fx/fx-inbox-view-rail';
import { railKeyForTeam, type InboxRailEntry } from './inbox-rail-entries';
import { InboxViewDialog } from './inbox-view-dialog';
import { entryToOption, useInboxViewRail } from './use-inbox-view-rail';

export interface InboxViewRailProps {
  workspaceId: string | null;
  filters: ConversationFilters;
  setFilters: (patch: Partial<ConversationFilters>) => void;
  variant?: 'sidebar' | 'select';
  className?: string;
}

export function InboxViewRail(props: InboxViewRailProps) {
  // Foundryx UIUX switch (playbook-uiux.md): the playbook rail. Off renders
  // the legacy body below, unchanged.
  return useFx() ? <FxInboxViewRail {...props} /> : <InboxViewRailLegacy {...props} />;
}

function InboxViewRailLegacy({ workspaceId, filters, setFilters, variant = 'sidebar', className }: InboxViewRailProps) {
  const {
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
  } = useInboxViewRail(workspaceId, filters, setFilters);

  if (variant === 'select') {
    const groups: SearchSelectGroup[] = [
      { label: 'Inbox', options: entries.filter((e) => e.kind === 'default').map(entryToOption) },
      { label: 'Lifecycle', options: entries.filter((e) => e.kind === 'lifecycle').map(entryToOption) },
      ...(entries.some((e) => e.kind === 'view')
        ? [{ label: 'Views', options: entries.filter((e) => e.kind === 'view').map(entryToOption) }]
        : []),
      ...(entries.some((e) => e.kind === 'team' && e.scope === 'mine')
        ? [{ label: 'My teams', options: entries.filter((e) => e.kind === 'team' && e.scope === 'mine').map(entryToOption) }]
        : []),
      ...(entries.some((e) => e.kind === 'team' && e.scope === 'other')
        ? [{ label: 'All teams', options: entries.filter((e) => e.kind === 'team' && e.scope === 'other').map(entryToOption) }]
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

      {(myTeams.length > 0 || otherTeams.length > 0) && (
        <div>
          {myTeams.length > 0 && (
            <p className="mb-1 px-2.5 text-xs font-semibold text-muted-foreground uppercase">My teams</p>
          )}
          <nav className="flex flex-col gap-0.5">
            {myTeams.map((team) => (
              <div key={team.id}>
                <button
                  type="button"
                  onClick={() =>
                    select({ kind: 'team', key: railKeyForTeam(team.id, false), teamId: team.id, unassigned: false, label: team.name, scope: 'mine' })
                  }
                  className={cn(
                    PRESSED_CLASS,
                    'flex w-full items-center rounded-md px-2.5 py-1.5 text-start text-sm transition-colors hover:bg-accent',
                    selectedKey === railKeyForTeam(team.id, false) && 'bg-accent font-medium text-accent-foreground',
                  )}
                  data-testid={`rail-${railKeyForTeam(team.id, false)}`}
                >
                  <span className="truncate">{team.name}</span>
                </button>
                <button
                  type="button"
                  onClick={() =>
                    select({ kind: 'team', key: railKeyForTeam(team.id, true), teamId: team.id, unassigned: true, label: `${team.name} - Unassigned`, scope: 'mine' })
                  }
                  className={cn(
                    PRESSED_CLASS,
                    'flex w-full items-center rounded-md py-1 ps-6 pe-2.5 text-start text-xs text-muted-foreground transition-colors hover:bg-accent',
                    selectedKey === railKeyForTeam(team.id, true) && 'bg-accent font-medium text-foreground',
                  )}
                  data-testid={`rail-${railKeyForTeam(team.id, true)}`}
                >
                  Unassigned
                </button>
              </div>
            ))}
          </nav>
          {otherTeams.length > 0 && (
            <>
              <p className="mt-2 mb-1 px-2.5 text-xs font-semibold text-muted-foreground uppercase">All teams</p>
              <nav className="flex flex-col gap-0.5">
                {otherTeams.map((team) => (
                  <div key={team.id}>
                    <button
                      type="button"
                      onClick={() =>
                        select({ kind: 'team', key: railKeyForTeam(team.id, false), teamId: team.id, unassigned: false, label: team.name, scope: 'other' })
                      }
                      className={cn(
                        PRESSED_CLASS,
                        'flex w-full items-center rounded-md px-2.5 py-1.5 text-start text-sm transition-colors hover:bg-accent',
                        selectedKey === railKeyForTeam(team.id, false) && 'bg-accent font-medium text-accent-foreground',
                      )}
                      data-testid={`rail-${railKeyForTeam(team.id, false)}`}
                    >
                      <span className="truncate">{team.name}</span>
                    </button>
                    <button
                      type="button"
                      onClick={() =>
                        select({ kind: 'team', key: railKeyForTeam(team.id, true), teamId: team.id, unassigned: true, label: `${team.name} - Unassigned`, scope: 'other' })
                      }
                      className={cn(
                        PRESSED_CLASS,
                        'flex w-full items-center rounded-md py-1 ps-6 pe-2.5 text-start text-xs text-muted-foreground transition-colors hover:bg-accent',
                        selectedKey === railKeyForTeam(team.id, true) && 'bg-accent font-medium text-foreground',
                      )}
                      data-testid={`rail-${railKeyForTeam(team.id, true)}`}
                    >
                      Unassigned
                    </button>
                  </div>
                ))}
              </nav>
            </>
          )}
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
