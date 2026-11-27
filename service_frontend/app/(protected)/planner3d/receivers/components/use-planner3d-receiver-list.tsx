'use client';

import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Trash2 } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { ClampedText } from '@/components/platform/clamped-text';
import { OverflowPills } from '@/components/platform/overflow-pills';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import type { ResourceAction, ResourceListConfig } from '@/components/platform/resource-list';
import type { ListQuery, ListResult } from '@/types/resource';
import { PLANNER3D_EVENT_LABELS, type Planner3dEvent, type Planner3dReceiverItem } from '@/types/planner3d';
import { useDatetime } from '@/hooks/use-datetime';
import { applyClientQuery, type ClientListSpec } from '@/lib/client-list-query';
import { toCsv } from '@/lib/csv';
import { planner3dService } from '@/services/planner3d-service';

const MANAGE = 'planner3d.webhooks.manage';

const eventLabels = (events: Planner3dEvent[]) => events.map((e) => PLANNER3D_EVENT_LABELS[e] ?? e);

const spec: ClientListSpec<Planner3dReceiverItem> = {
  searchText: (r) => [r.url, ...eventLabels(r.events)],
  value: (r, field) => {
    switch (field) {
      case 'url':
        return r.url.toLowerCase();
      case 'events':
        return r.events;
      case 'created':
        return r.createdAt;
      case 'lastSuccess':
        return r.lastSuccessAt;
      default:
        return null;
    }
  },
};

const stop = (e: React.MouseEvent) => e.stopPropagation();

/**
 * 3D Planner webhook receivers (lane PLANNER-3D-S1) on the Resource shell, cloned
 * from Lead Capture's. Row action: Remove (grace-window
 * `planner3d_receivers.remove`). Create opens the add dialog.
 */
export function usePlanner3dReceiverList(
  onCreate: () => void,
  onChanged: () => void,
  /** Bump to refetch (after an Add) without remounting the list, which would
   *  restore the address bar's state from page load. */
  refreshKey = 0,
): ResourceListConfig<Planner3dReceiverItem> {
  const { formatDmyDateTime } = useDatetime();

  const actions = useMemo<ResourceAction<Planner3dReceiverItem>[]>(
    () => [
      {
        id: 'remove',
        label: 'Remove',
        icon: Trash2,
        tone: 'destructive',
        permission: MANAGE,
        surfaces: { row: true },
        isVisible: (rows) => rows.length === 1,
        deferred: { actionKey: 'planner3d_receivers.remove', entityType: 'planner3d_receiver' },
      },
    ],
    [],
  );

  return useMemo<ResourceListConfig<Planner3dReceiverItem>>(() => {
    const columns: ColumnDef<Planner3dReceiverItem>[] = [
      {
        id: 'url',
        accessorFn: (r) => r.url,
        meta: { headerTitle: 'URL' },
        header: ({ column }) => <DataGridColumnHeader title="URL" column={column} />,
        cell: ({ row }) => <ClampedText text={row.original.url} lines={1} className="font-medium" />,
        size: 290,
        enableSorting: true,
      },
      {
        id: 'events',
        accessorFn: (r) => eventLabels(r.events).join(', '),
        meta: { headerTitle: 'Events' },
        header: ({ column }) => <DataGridColumnHeader title="Events" column={column} />,
        cell: ({ row }) => (
          <OverflowPills
            items={eventLabels(row.original.events)}
            keyFor={(label) => label}
            renderPill={(label) => (
              <Badge variant="secondary" appearance="light" size="sm">
                {label}
              </Badge>
            )}
          />
        ),
        size: 190,
        enableSorting: true,
      },
      {
        id: 'created',
        accessorFn: (r) => r.createdAt,
        meta: { headerTitle: 'Added' },
        header: ({ column }) => <DataGridColumnHeader title="Added" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">{formatDmyDateTime(row.original.createdAt)}</span>
        ),
        size: 180,
        enableSorting: true,
      },
      {
        id: 'lastSuccess',
        accessorFn: (r) => r.lastSuccessAt,
        meta: { headerTitle: 'Last delivered' },
        header: ({ column }) => <DataGridColumnHeader title="Last delivered" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">
            {row.original.lastSuccessAt ? formatDmyDateTime(row.original.lastSuccessAt) : '-'}
          </span>
        ),
        size: 190,
        enableSorting: true,
      },
      {
        id: 'actions',
        meta: { reorderable: false },
        header: () => null,
        cell: ({ row, table }) => {
          const meta = table.options.meta;
          const reload = () => {
            meta?.reload?.();
            onChanged();
          };
          return (
            <div onClick={stop} className="flex justify-end">
              <ActionMenu
                actions={actions}
                rows={[row.original]}
                runtime={{ ctx: meta?.resourceCtx, index: (meta?.pageStartIndex ?? 0) + row.index, reload }}
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

    const fetcher = async (query: ListQuery): Promise<ListResult<Planner3dReceiverItem>> => {
      // A new refreshKey = a new fetcher, which the list refetches with its
      // current query (no remount).
      void refreshKey;
      return applyClientQuery(await planner3dService.listReceivers(), query, spec);
    };

    const exporter = async (query: ListQuery): Promise<string> => {
      const { data } = await fetcher({ ...query, page: 0, pageSize: 10_000 });
      return toCsv(
        ['URL', 'Events', 'Added', 'Last delivered'],
        data.map((r) => [
          r.url,
          eventLabels(r.events).join(', '),
          formatDmyDateTime(r.createdAt),
          r.lastSuccessAt ? formatDmyDateTime(r.lastSuccessAt) : '-',
        ]),
      );
    };

    return {
      viewKey: 'planner3d.receivers',
      columns,
      getRowId: (r) => r.id,
      rowHref: () => '#',
      fetcher,
      exporter,
      filterFields: [
        {
          field: 'events',
          label: 'Events',
          type: 'enum',
          options: (Object.keys(PLANNER3D_EVENT_LABELS) as Planner3dEvent[]).map((value) => ({
            value,
            label: PLANNER3D_EVENT_LABELS[value],
          })),
        },
      ],
      exportColumns: [
        { id: 'url', label: 'URL' },
        { id: 'events', label: 'Events' },
        { id: 'created', label: 'Added' },
        { id: 'lastSuccess', label: 'Last delivered' },
      ],
      actions,
      searchPlaceholder: 'Search receivers…',
      defaultSort: { id: 'created', desc: false },
      exportFilename: 'planner3d-receivers',
      enableStatusViews: false,
      urlState: true,
      createLabel: 'Create',
      createPermission: MANAGE,
      onCreate,
      onDeferredCommitted: () => onChanged(),
    };
  }, [actions, formatDmyDateTime, onCreate, onChanged, refreshKey]);
}
