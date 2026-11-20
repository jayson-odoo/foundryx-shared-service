'use client';

import { useMemo } from 'react';
import { useRouter } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import {
  DataGridTableRowSelect,
  DataGridTableRowSelectAll,
} from '@/components/ui/data-grid-table';
import { StatusBadge } from '@/components/platform/status-badge';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import { ClampedText } from '@/components/platform/clamped-text';
import type { ResourceListConfig } from '@/components/platform/resource-list';
import { teamService } from '@/services/team-service';
import { useDatetime } from '@/hooks/use-datetime';
import { useTerminology } from '@/hooks/use-terminology';
import type { FilterFieldDef } from '@/types/resource';
import type { Team } from '@/types/team';
import { MemberPills } from './member-pills';
import { TEAM_STATUS_REGISTRY, teamStatus } from './team-status';
import { useTeamActions } from './use-team-actions';
import { teamFormPath, teamNewPath } from './paths';

const stop = (e: React.MouseEvent) => e.stopPropagation();

// Whitelist mirrors the backend's `_TEAM_FILTER_COLUMNS`
// (`app/services/team_service.py`) - keep the two in sync.
const FILTER_FIELDS: FilterFieldDef[] = [
  { field: 'name', label: 'Name', type: 'text' },
  { field: 'description', label: 'Description', type: 'text' },
  { field: 'isActive', label: 'Active', type: 'bool' },
];

/** Teams list config (plan 28, D-A8-2) - a literal Resource-shell clone of
 * `useUsersListConfig`: no hand-rolled table anywhere in this diff. */
export function useTeamsListConfig(): ResourceListConfig<Team> {
  const { formatDate } = useDatetime();
  const router = useRouter();
  const actions = useTeamActions();
  const { label, labelPlural } = useTerminology();
  const singular = label('team');
  const plural = labelPlural('team');

  return useMemo<ResourceListConfig<Team>>(() => {
    const columns: ColumnDef<Team>[] = [
      {
        id: 'select',
        meta: { reorderable: false },
        header: () => (
          <div onClick={stop}>
            <DataGridTableRowSelectAll />
          </div>
        ),
        cell: ({ row }) => (
          <div onClick={stop}>
            <DataGridTableRowSelect row={row} />
          </div>
        ),
        size: 48,
        enableSorting: false,
        enableHiding: false,
        enableResizing: false,
      },
      {
        id: 'name',
        accessorFn: (row) => row.name,
        meta: { headerTitle: 'Name' },
        header: ({ column }) => <DataGridColumnHeader title="Name" column={column} />,
        cell: ({ row }) => (
          <span className="font-medium text-foreground">{row.original.name}</span>
        ),
        size: 220,
        enableSorting: true,
      },
      {
        id: 'description',
        accessorFn: (row) => row.description,
        meta: { headerTitle: 'Description' },
        header: ({ column }) => <DataGridColumnHeader title="Description" column={column} />,
        cell: ({ row }) => (
          <ClampedText
            text={row.original.description ?? '-'}
            lines={1}
            className="text-sm text-muted-foreground"
          />
        ),
        size: 280,
        enableSorting: false,
      },
      {
        id: 'members',
        accessorFn: (row) => row.members.map((m) => m.name).join(', '),
        meta: { headerTitle: 'Members' },
        header: ({ column }) => <DataGridColumnHeader title="Members" column={column} />,
        cell: ({ row }) => <MemberPills members={row.original.members} />,
        size: 260,
        enableSorting: false,
      },
      {
        id: 'status',
        accessorFn: (row) => teamStatus(row.isActive),
        meta: { headerTitle: 'Status' },
        header: ({ column }) => <DataGridColumnHeader title="Status" column={column} />,
        cell: ({ row }) => (
          <StatusBadge status={teamStatus(row.original.isActive)} registry={TEAM_STATUS_REGISTRY} />
        ),
        size: 120,
        // No backend sort column for `status` (`_SORT_COLUMNS` only knows
        // name/sortOrder/createdAt) - keep sortable columns limited to ones
        // the server can actually order by.
        enableSorting: false,
      },
      {
        id: 'created',
        accessorFn: (row) => row.createdAt,
        meta: { headerTitle: 'Created' },
        header: ({ column }) => <DataGridColumnHeader title="Created" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">{formatDate(row.original.createdAt)}</span>
        ),
        size: 150,
        enableSorting: true,
      },
      {
        id: 'actions',
        meta: { reorderable: false },
        header: () => null,
        cell: ({ row, table }) => {
          const meta = table.options.meta;
          const index = (meta?.pageStartIndex ?? 0) + row.index;
          return (
            <div onClick={stop} className="flex justify-end">
              <ActionMenu
                actions={actions}
                rows={[row.original]}
                runtime={{ ctx: meta?.resourceCtx, index, reload: meta?.reload ?? (() => {}) }}
                surface="row"
              />
            </div>
          );
        },
        size: 60,
        enableSorting: false,
        enableHiding: false,
        enableResizing: false,
      },
    ];

    return {
      viewKey: 'teams.list',
      pageTitle: plural,
      columns,
      getRowId: (t) => t.id,
      rowHref: (t) => teamFormPath(t.id),
      fetcher: (q) => teamService.list(q),
      filterFields: FILTER_FIELDS,
      exportColumns: [],
      actions,
      searchPlaceholder: `Search ${plural.toLowerCase()}…`,
      searchHints: ['Name', 'Description'],
      defaultSort: { id: 'name', desc: false },
      // Teams have no soft-trash concept (D-A8-19) - Active/Inactive is a
      // filterable FIELD (status), not the shell's Active|Trashed view.
      enableStatusViews: false,
      createLabel: `Add ${singular.toLowerCase()}`,
      createPermission: 'teams.manage',
      onCreate: () => router.push(teamNewPath),
    };
  }, [actions, router, formatDate, singular, plural]);
}
