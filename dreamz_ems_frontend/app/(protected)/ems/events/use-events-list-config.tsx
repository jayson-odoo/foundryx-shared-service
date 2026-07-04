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
import type { Project } from '@/types/ems';
import type { StatusNodeData, StatusTransition } from '@/types/status-engine';

const stop = (e: React.MouseEvent) => e.stopPropagation();

export interface EventsConfigCtx {
  onCreate: () => void;
  onEdit: (row: Project) => void;
  statuses: StatusNodeData[];
  transitions: StatusTransition[];
}

/** Events on the full Resource shell — search · sort · column prefs · select ·
 * export. The lifecycle status (Draft/Planning/Active/…) shows as a column and
 * changes via the row "…" / bulk "…" — both surface the SAME graph-driven next
 * states (one action per reachable target, shown for bulk only when every
 * selected row can reach it). AUTO edges (derived status) fire by themselves and
 * are never offered as a manual click. (Events are created from templates; no
 * bulk import.) */
export function useEventsListConfig(ctx: EventsConfigCtx): ResourceListConfig<Project> {
  const { onCreate, onEdit, statuses, transitions } = ctx;
  const { formatDateTime } = useDatetime();
  const { label, labelPlural } = useTerminology();
  const singular = label('project');
  const plural = labelPlural('project');

  return useMemo<ResourceListConfig<Project>>(() => {
    const statusLabel = new Map(statuses.map((s) => [s.id, s.label]));

    // Manual transitions only — an AUTO edge is system-fired (derived status).
    const manual = transitions.filter((t) => t.triggerMode !== 'auto');
    const byTarget = new Map<string, StatusTransition[]>();
    for (const t of manual) {
      const g = byTarget.get(t.toStatusId);
      if (g) g.push(t);
      else byTarget.set(t.toStatusId, [t]);
    }
    const edgeForRow = (edges: StatusTransition[], r: Project) =>
      edges.find((e) => e.fromStatusId === r.statusId);

    const transitionActions: ResourceAction<Project>[] = Array.from(
      byTarget,
      ([toId, edges]) => ({
        id: `move-${toId}`,
        label: statusLabel.get(toId) || edges[0].label, // bare target status name
        icon: ArrowRight,
        surfaces: { row: true, form: false, bulk: true },
        permission: 'projects.manage',
        isVisible: (rows) =>
          rows.length > 0 && rows.every((r) => Boolean(edgeForRow(edges, r))),
        run: async (rows, rt) => {
          const fired = (
            await Promise.all(
              rows.map(async (r) => {
                const edge = edgeForRow(edges, r);
                if (!edge) return false;
                try {
                  await emsService.transitionProject(r.id, toId);
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

    const editAction: ResourceAction<Project> = {
      id: 'edit',
      label: 'Open',
      icon: Pencil,
      surfaces: { row: true, form: false, bulk: false },
      permission: 'projects.read',
      run: ([row]) => {
        if (row) onEdit(row);
      },
    };

    const rowMenuActions = [...transitionActions, editAction];

    const columns: ColumnDef<Project>[] = [
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
        id: 'title',
        accessorFn: (r) => r.title,
        meta: { headerTitle: 'Title' },
        header: ({ column }) => <DataGridColumnHeader title="Title" column={column} />,
        cell: ({ row }) => <span className="font-medium">{row.original.title}</span>,
        size: 280,
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
        // Calendar date — render the "YYYY-MM-DD" directly (NOT via the tz
        // formatter, which would shift the day in the session tz).
        id: 'startDate',
        accessorFn: (r) => r.startDate,
        meta: { headerTitle: 'Start' },
        header: ({ column }) => <DataGridColumnHeader title="Start" column={column} />,
        cell: ({ row }) => (
          <span className="text-muted-foreground">{row.original.startDate ?? '—'}</span>
        ),
        size: 120,
        enableSorting: true,
      },
      {
        id: 'endDate',
        accessorFn: (r) => r.endDate,
        meta: { headerTitle: 'End' },
        header: ({ column }) => <DataGridColumnHeader title="End" column={column} />,
        cell: ({ row }) => (
          <span className="text-muted-foreground">{row.original.endDate ?? '—'}</span>
        ),
        size: 120,
        enableSorting: true,
      },
      {
        id: 'createdAt',
        accessorFn: (r) => r.createdAt,
        meta: { headerTitle: 'Created' },
        header: ({ column }) => <DataGridColumnHeader title="Created" column={column} />,
        cell: ({ row }) => (
          <span className="text-muted-foreground">{formatDateTime(row.original.createdAt)}</span>
        ),
        size: 160,
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
      viewKey: 'ems.events',
      getRowId: (r) => r.id,
      rowHref: (r) => `/ems/events/${r.id}`,
      fetcher: (q) => emsService.listProjectsQuery(q),
      exporter: (q, cols, ids) => emsService.exportProjects(q, cols, ids),
      searchPlaceholder: `Search ${plural.toLowerCase()}…`,
      searchHints: ['Title'],
      defaultSort: { id: 'createdAt', desc: true },
      exportFilename: 'events',
      enableStatusViews: false,
      createLabel: `New ${singular.toLowerCase()}`,
      createPermission: 'projects.manage',
      onCreate,
      columns,
      // Bulk "…": per-target transitions (shown only when every selected row can reach it).
      actions: transitionActions,
      filterFields: [],
      exportColumns: [
        { id: 'id', label: 'ID' },
        { id: 'title', label: 'Title' },
        { id: 'brief', label: 'Brief' },
        { id: 'startDate', label: 'Start' },
        { id: 'endDate', label: 'End' },
        { id: 'createdAt', label: 'Created' },
      ],
    };
  }, [formatDateTime, onCreate, onEdit, statuses, transitions, singular, plural]);
}
