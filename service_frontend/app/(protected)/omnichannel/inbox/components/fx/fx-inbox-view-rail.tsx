'use client';

/**
 * The inbox views rail with the Foundryx UIUX switch on (slice W1-INBOX).
 * Same entries, selection, saved views and delete as the legacy rail (one
 * shared hook, `useInboxViewRail`); drawn the playbook way: entries lift on
 * hover, the chosen one carries the link tint, and Save view and the view
 * menu are icon actions with tooltips.
 *
 * No counts beside the entries: the inbox API returns no per-view or
 * per-stage totals, and the slice adds no backend work (owner choice: show
 * counts only if the API already has them).
 */
import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import {
  FxIconAction,
  FxIconActionButton,
} from '@/components/fx/actions/icon-action';
import { FxTooltip } from '@/components/fx/fx-tooltip';
import {
  SearchSelect,
  type SearchSelectGroup,
} from '@/components/platform/search-select';
import {
  railKeyForTeam,
  type InboxRailEntry,
  type RailTeam,
} from '../inbox-rail-entries';
import { InboxViewDialog } from '../inbox-view-dialog';
import type { InboxViewRailProps } from '../inbox-view-rail';
import { entryToOption, useInboxViewRail } from '../use-inbox-view-rail';

const ENTRY = cn(
  PRESSED_CLASS,
  'flex min-h-9 w-full min-w-0 items-center rounded-(--fx-r-m) px-2.5 text-start text-sm text-(--fx-ink-2)',
  'transition-[translate,background-color] duration-(--fx-t-hover) ease-(--fx-ease-out) hover:-translate-y-0.5 hover:bg-(--fx-surface-2) motion-reduce:hover:translate-y-0',
);
const ENTRY_ON =
  'bg-(--fx-link-bg) font-semibold text-(--fx-link) hover:bg-(--fx-link-bg)';
const HEADING =
  'mb-1 flex min-h-7 items-center justify-between px-2.5 text-xs font-semibold text-(--fx-ink-3)';

function RailButton({
  railKey,
  selectedKey,
  onClick,
  nested = false,
  children,
}: {
  railKey: string;
  selectedKey: string;
  onClick: () => void;
  nested?: boolean;
  children: ReactNode;
}) {
  const on = selectedKey === railKey;
  return (
    <button
      type="button"
      onClick={onClick}
      aria-current={on ? 'true' : undefined}
      className={cn(ENTRY, nested && 'min-h-8 ps-6 text-xs', on && ENTRY_ON)}
      data-testid={`rail-${railKey}`}
    >
      <span className="truncate">{children}</span>
    </button>
  );
}

export function FxInboxViewRail({
  workspaceId,
  filters,
  setFilters,
  variant = 'sidebar',
  className,
}: InboxViewRailProps) {
  const rail = useInboxViewRail(workspaceId, filters, setFilters);
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
  } = rail;

  const dialog = (
    <InboxViewDialog
      open={dialogOpen}
      onOpenChange={setDialogOpen}
      view={editingView}
      canShare={canManageShared}
      onCreate={async (values) =>
        selectCreatedView(await create({ ...values, filter: currentFilter }))
      }
      onUpdate={(id, values) => update(id, values)}
    />
  );

  if (variant === 'select') {
    const byKind = (pick: (e: InboxRailEntry) => boolean) =>
      entries.filter(pick).map(entryToOption);
    const groups: SearchSelectGroup[] = [
      { label: 'Inbox', options: byKind((e) => e.kind === 'default') },
      { label: 'Lifecycle', options: byKind((e) => e.kind === 'lifecycle') },
      { label: 'Views', options: byKind((e) => e.kind === 'view') },
      {
        label: 'My teams',
        options: byKind((e) => e.kind === 'team' && e.scope === 'mine'),
      },
      {
        label: 'All teams',
        options: byKind((e) => e.kind === 'team' && e.scope === 'other'),
      },
    ].filter((g) => g.options.length > 0);
    return (
      <div
        className={cn('flex items-center gap-2', className)}
        data-testid="inbox-view-select"
      >
        <SearchSelect
          groups={groups}
          value={selectedKey}
          onChange={(key) => {
            const entry = entries.find((e) => e.key === key);
            if (entry) select(entry);
          }}
          ariaLabel="View"
          className="min-w-0 flex-1"
        />
        <FxIconAction
          label="Save view"
          icon="add"
          mini
          onClick={openCreate}
          data-testid="save-view-trigger"
        />
        {dialog}
      </div>
    );
  }

  const teamGroup = (teams: RailTeam[], scope: 'mine' | 'other') =>
    teams.map((team) => (
      <div key={team.id} className="flex flex-col gap-0.5">
        <RailButton
          railKey={railKeyForTeam(team.id, false)}
          selectedKey={selectedKey}
          onClick={() =>
            select({
              kind: 'team',
              key: railKeyForTeam(team.id, false),
              teamId: team.id,
              unassigned: false,
              label: team.name,
              scope,
            })
          }
        >
          {team.name}
        </RailButton>
        <RailButton
          railKey={railKeyForTeam(team.id, true)}
          selectedKey={selectedKey}
          nested
          onClick={() =>
            select({
              kind: 'team',
              key: railKeyForTeam(team.id, true),
              teamId: team.id,
              unassigned: true,
              label: `${team.name} - Unassigned`,
              scope,
            })
          }
        >
          Unassigned
        </RailButton>
      </div>
    ));

  return (
    <div
      className={cn(
        'flex h-full flex-col gap-4 overflow-y-auto p-2.5',
        className,
      )}
      data-testid="inbox-view-rail"
      data-fx-inbox-rail=""
    >
      <nav className="flex flex-col gap-0.5" aria-label="Inbox">
        {entries
          .filter((e) => e.kind === 'default')
          .map((e) => (
            <RailButton
              key={e.key}
              railKey={e.key}
              selectedKey={selectedKey}
              onClick={() => select(e)}
            >
              {e.label}
            </RailButton>
          ))}
      </nav>

      {stages.length > 0 && (
        <nav aria-label="Lifecycle">
          <p className={HEADING}>Lifecycle</p>
          <div className="flex flex-col gap-0.5">
            {entries
              .filter((e) => e.kind === 'lifecycle')
              .map((e) => (
                <RailButton
                  key={e.key}
                  railKey={e.key}
                  selectedKey={selectedKey}
                  onClick={() => select(e)}
                >
                  {e.label}
                </RailButton>
              ))}
          </div>
        </nav>
      )}

      {(myTeams.length > 0 || otherTeams.length > 0) && (
        <nav aria-label="Teams">
          {myTeams.length > 0 && (
            <>
              <p className={HEADING}>My teams</p>
              <div className="flex flex-col gap-0.5">
                {teamGroup(myTeams, 'mine')}
              </div>
            </>
          )}
          {otherTeams.length > 0 && (
            <>
              <p className={cn(HEADING, 'mt-2')}>All teams</p>
              <div className="flex flex-col gap-0.5">
                {teamGroup(otherTeams, 'other')}
              </div>
            </>
          )}
        </nav>
      )}

      <nav aria-label="Views">
        <div className={cn(HEADING, 'pe-0')}>
          <span>Views</span>
          <FxIconAction
            label="Save view"
            icon="add"
            mini
            onClick={openCreate}
            data-testid="save-view-trigger"
          />
        </div>
        <div className="flex flex-col gap-0.5">
          {entries
            .filter(
              (e): e is Extract<InboxRailEntry, { kind: 'view' }> =>
                e.kind === 'view',
            )
            .map((e) => {
              const view = views.find((v) => v.id === e.viewId);
              // D-A3-11: the owner may always manage their own view; a SHARED
              // view or someone else's additionally needs `inbox_views.manage`.
              const mayManage = view
                ? (currentUserId !== null &&
                    view.ownerUserId === currentUserId) ||
                  canManageShared
                : false;
              const on = selectedKey === e.key;
              return (
                <div
                  key={e.key}
                  className="group/view relative flex items-center"
                >
                  <button
                    type="button"
                    onClick={() => select(e)}
                    aria-current={on ? 'true' : undefined}
                    className={cn(ENTRY, mayManage && 'pe-10', on && ENTRY_ON)}
                    data-testid={`rail-view-${e.viewId}`}
                  >
                    <span className="truncate">{e.label}</span>
                    {e.isShared && (
                      <span className="ms-1.5 shrink-0 text-xs font-normal text-(--fx-ink-3)">
                        (shared)
                      </span>
                    )}
                  </button>
                  {mayManage && view && (
                    <DropdownMenu>
                      <FxTooltip label={`Manage view ${e.label}`}>
                        <DropdownMenuTrigger asChild>
                          <FxIconActionButton
                            label={`Manage view ${e.label}`}
                            icon="more"
                            mini
                            className="absolute end-0 min-h-8 min-w-8 border-transparent bg-transparent opacity-0 shadow-none group-hover/view:opacity-100 focus-visible:opacity-100 data-[state=open]:opacity-100 pointer-coarse:opacity-100"
                            data-testid={`rail-view-menu-${e.viewId}`}
                          />
                        </DropdownMenuTrigger>
                      </FxTooltip>
                      <DropdownMenuContent align="end">
                        <DropdownMenuItem onClick={() => openEdit(view)}>
                          Rename view
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          className="text-(--fx-act)"
                          onClick={() => void deleteView(view)}
                        >
                          Delete view
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  )}
                </div>
              );
            })}
        </div>
      </nav>

      {dialog}
    </div>
  );
}
