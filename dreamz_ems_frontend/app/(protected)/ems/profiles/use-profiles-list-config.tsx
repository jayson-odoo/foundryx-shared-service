'use client';

import { useMemo } from 'react';
import { toast } from 'sonner';
import type { ColumnDef } from '@tanstack/react-table';
import { ArrowRight, Pencil } from 'lucide-react';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import {
  DataGridTableRowSelect,
  DataGridTableRowSelectAll,
} from '@/components/ui/data-grid-table';
import { Badge } from '@/components/ui/badge';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import type { ResourceAction, ResourceListConfig } from '@/components/platform/resource-list';
import { useDatetime } from '@/hooks/use-datetime';
import { useTerminology } from '@/hooks/use-terminology';
import { emsService } from '@/services/ems-service';
import type { Profile } from '@/types/ems';
import type { StatusNodeData, StatusTransition } from '@/types/status-engine';

const stop = (e: React.MouseEvent) => e.stopPropagation();

export interface ProfilesConfigCtx {
  onCreate: () => void;
  onEdit: (row: Profile) => void;
  statuses: StatusNodeData[];
  transitions: StatusTransition[];
}

/** Profiles on the full Resource shell — search · sort · column prefs · select ·
 * export · import. The tier-1 status (Active/Suspended/Blacklisted) shows as a
 * column and changes via the row "…" / bulk "…" — both surface the SAME
 * graph-driven next states (one action per reachable target). Bulk shows a
 * target only when EVERY selected row can reach it (mirrors the Tenants
 * console). AUTO edges (derived status) fire by themselves and are never
 * offered as a manual click. */
export function useProfilesListConfig(ctx: ProfilesConfigCtx): ResourceListConfig<Profile> {
  const { onCreate, onEdit, statuses, transitions } = ctx;
  const { formatDateTime } = useDatetime();
  const { label, labelPlural } = useTerminology();
  const singular = label('profile');
  const plural = labelPlural('profile');

  return useMemo<ResourceListConfig<Profile>>(() => {
    const statusLabel = new Map(statuses.map((s) => [s.id, s.label]));

    // Manual transitions only — an AUTO edge is system-fired (derived status),
    // never a manual target (mirrors the backend available_transitions).
    const manual = transitions.filter((t) => t.triggerMode !== 'auto');

    // One action per reachable target status, grouped across from-statuses so a
    // mixed selection bulk-moves (each row fires ITS own edge to that target).
    const byTarget = new Map<string, StatusTransition[]>();
    for (const t of manual) {
      const g = byTarget.get(t.toStatusId);
      if (g) g.push(t);
      else byTarget.set(t.toStatusId, [t]);
    }
    const edgeForRow = (edges: StatusTransition[], r: Profile) =>
      edges.find((e) => e.fromStatusId === r.statusId);

    const transitionActions: ResourceAction<Profile>[] = Array.from(
      byTarget,
      ([toId, edges]) => ({
        id: `move-${toId}`,
        // Bare target status name (user mandate — no "Move to" prefix).
        label: statusLabel.get(toId) || edges[0].label,
        icon: ArrowRight,
        surfaces: { row: true, form: false, bulk: true },
        permission: 'profiles.manage',
        isVisible: (rows) =>
          rows.length > 0 && rows.every((r) => Boolean(edgeForRow(edges, r))),
        run: async (rows, rt) => {
          // Count what actually fired — a row whose edge vanished between the
          // visibility check and run is skipped, not silently counted.
          const fired = (
            await Promise.all(
              rows.map(async (r) => {
                const edge = edgeForRow(edges, r);
                if (!edge) return false;
                try {
                  await emsService.transitionProfile(r.id, toId);
                  return true;
                } catch {
                  return false;
                }
              }),
            )
          ).filter(Boolean).length;
          const skipped = rows.length - fired;
          const noun = (fired === 1 ? singular : plural).toLowerCase();
          if (fired === 0) {
            toast.error('Could not change the status.');
          } else if (skipped > 0) {
            toast.warning(`${fired} ${noun} updated, ${skipped} skipped.`);
          } else {
            toast.success(`${fired} ${noun} updated.`);
          }
          rt?.reload?.();
        },
      }),
    );

    const editAction: ResourceAction<Profile> = {
      id: 'edit',
      label: 'Open',
      icon: Pencil,
      surfaces: { row: true, form: false, bulk: false },
      permission: 'profiles.read',
      run: ([row]) => {
        if (row) onEdit(row);
      },
    };

    const rowMenuActions = [...transitionActions, editAction];

    const columns: ColumnDef<Profile>[] = [
      {
        id: 'select',
        meta: { reorderable: false },
        header: () => <div onClick={stop}><DataGridTableRowSelectAll /></div>,
        cell: ({ row }) => <div onClick={stop}><DataGridTableRowSelect row={row} /></div>,
        size: 48,
        enableSorting: false,
        enableHiding: false,
        enableResizing: false,
      },
      {
        id: 'fullName',
        accessorFn: (r) => r.fullName,
        meta: { headerTitle: 'Name' },
        header: ({ column }) => <DataGridColumnHeader title="Name" column={column} />,
        cell: ({ row }) => <span className="font-medium">{row.original.fullName ?? '—'}</span>,
        size: 200,
        enableSorting: true,
      },
      {
        id: 'email',
        accessorFn: (r) => r.email,
        meta: { headerTitle: 'Email' },
        header: ({ column }) => <DataGridColumnHeader title="Email" column={column} />,
        cell: ({ row }) => <span>{row.original.email}</span>,
        size: 220,
        enableSorting: true,
      },
      {
        id: 'status',
        accessorFn: (r) => (r.statusId ? statusLabel.get(r.statusId) ?? '' : ''),
        meta: { headerTitle: 'Status' },
        header: ({ column }) => <DataGridColumnHeader title="Status" column={column} />,
        cell: ({ row }) =>
          row.original.statusId && statusLabel.get(row.original.statusId) ? (
            <Badge variant="primary" appearance="light" size="sm">
              {statusLabel.get(row.original.statusId)}
            </Badge>
          ) : (
            <span className="text-muted-foreground">—</span>
          ),
        size: 140,
        enableSorting: false,
      },
      {
        id: 'organization',
        accessorFn: (r) => r.organization,
        meta: { headerTitle: 'Organization' },
        header: ({ column }) => <DataGridColumnHeader title="Organization" column={column} />,
        cell: ({ row }) => (
          <span className="text-muted-foreground">{row.original.organization ?? '—'}</span>
        ),
        size: 160,
        enableSorting: false,
      },
      {
        id: 'createdAt',
        accessorFn: (r) => r.createdAt,
        meta: { headerTitle: 'Created' },
        header: ({ column }) => <DataGridColumnHeader title="Created" column={column} />,
        cell: ({ row }) => (
          <span className="text-muted-foreground">{formatDateTime(row.original.createdAt)}</span>
        ),
        size: 150,
        enableSorting: true,
      },
      {
        id: 'actions',
        meta: { reorderable: false },
        header: () => null,
        cell: ({ row, table }) => {
          const reload = table.options.meta?.reload ?? (() => {});
          return (
            <div onClick={stop} className="flex justify-end">
              <ActionMenu
                actions={rowMenuActions}
                rows={[row.original]}
                runtime={{ reload }}
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
      viewKey: 'ems.profiles',
      getRowId: (r) => r.id,
      rowHref: (r) => `/ems/profiles/${r.id}`,
      fetcher: (q) => emsService.listProfilesQuery(q),
      exporter: (q, cols, ids) => emsService.exportProfiles(q, cols, ids),
      searchPlaceholder: `Search ${plural.toLowerCase()}…`,
      searchHints: ['Name', 'Email'],
      defaultSort: { id: 'createdAt', desc: true },
      exportFilename: 'profiles',
      statusViewLabels: { active: 'Active', trashed: 'Trashed' },
      createLabel: `New ${singular.toLowerCase()}`,
      createPermission: 'profiles.manage',
      onCreate,
      importer: { entityType: 'profile', writePermission: 'profiles.manage' },
      columns,
      // Bulk "…": the per-target transition actions (shown only when every
      // selected row can reach that target).
      actions: transitionActions,
      filterFields: [],
      exportColumns: [
        { id: 'id', label: 'ID' },
        { id: 'email', label: 'Email' },
        { id: 'fullName', label: 'Name' },
        { id: 'phone', label: 'Phone' },
        { id: 'country', label: 'Country' },
        { id: 'organization', label: 'Organization' },
        { id: 'title', label: 'Title' },
        { id: 'createdAt', label: 'Created' },
      ],
    };
  }, [formatDateTime, onCreate, onEdit, statuses, transitions, singular, plural]);
}
