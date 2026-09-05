'use client';

import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { StatusBadge } from '@/components/platform/status-badge';
import { ClampedText } from '@/components/platform/clamped-text';
import type { ResourceListConfig } from '@/components/platform/resource-list';
import { useDatetime } from '@/hooks/use-datetime';
import type { BroadcastRecipient } from '@/types/omnichannel';
import type { FilterFieldDef, ListQuery } from '@/types/resource';
import { RECIPIENT_STATE_OPTIONS, RECIPIENT_STATE_REGISTRY } from './broadcast-status';
import { useBroadcastRecipients } from '@/hooks/use-broadcast-recipients';

const FILTER_FIELDS: FilterFieldDef[] = [
  { field: 'state', label: 'State', type: 'enum', options: RECIPIENT_STATE_OPTIONS },
];

/** Recipients tab list config (plan 29, AC-BRD-10) - an embedded `ResourceList`
 *  over `broadcast-service.recipients`, no detail page (`rowHref: '#'`). */
export function useRecipientsListConfig(
  workspaceId: string | null,
  broadcastId: string | null,
): ResourceListConfig<BroadcastRecipient> {
  const { formatDateTime } = useDatetime();
  const { fetcher } = useBroadcastRecipients(workspaceId, broadcastId);

  return useMemo<ResourceListConfig<BroadcastRecipient>>(() => {
    const columns: ColumnDef<BroadcastRecipient>[] = [
      {
        id: 'contact',
        accessorFn: (row) => row.contactName,
        meta: { headerTitle: 'Contact' },
        header: ({ column }) => <DataGridColumnHeader title="Contact" column={column} />,
        cell: ({ row }) => <ClampedText text={row.original.contactName} lines={1} className="font-medium" />,
        size: 200,
        enableSorting: false,
      },
      {
        id: 'phone',
        accessorFn: (row) => row.phone ?? '-',
        meta: { headerTitle: 'Phone' },
        header: ({ column }) => <DataGridColumnHeader title="Phone" column={column} />,
        cell: ({ row }) => <span className="text-muted-foreground">{row.original.phone ?? '-'}</span>,
        size: 150,
        enableSorting: false,
      },
      {
        id: 'state',
        accessorFn: (row) => row.state,
        meta: { headerTitle: 'State' },
        header: ({ column }) => <DataGridColumnHeader title="State" column={column} />,
        cell: ({ row }) => <StatusBadge status={row.original.state} registry={RECIPIENT_STATE_REGISTRY} />,
        size: 130,
        enableSorting: false,
      },
      {
        id: 'error',
        accessorFn: (row) => row.errorText ?? row.skipReason ?? '-',
        meta: { headerTitle: 'Error' },
        header: ({ column }) => <DataGridColumnHeader title="Error" column={column} />,
        cell: ({ row }) => {
          const text = row.original.errorText ?? (row.original.skipReason ? `Skipped: ${row.original.skipReason}` : '-');
          return <ClampedText text={text} lines={2} className="text-muted-foreground" />;
        },
        size: 260,
        enableSorting: false,
      },
      {
        id: 'attemptedAt',
        accessorFn: (row) => row.attemptedAt ?? '',
        meta: { headerTitle: 'Attempted at' },
        header: ({ column }) => <DataGridColumnHeader title="Attempted at" column={column} />,
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {row.original.attemptedAt ? formatDateTime(row.original.attemptedAt) : '-'}
          </span>
        ),
        size: 170,
        enableSorting: false,
      },
    ];

    return {
      viewKey: 'omnichannel.broadcasts.recipients',
      columns,
      getRowId: (row) => row.id,
      rowHref: () => '#',
      fetcher: (query: ListQuery) => {
        const state = query.filter?.rules.find((r) => r.kind === 'condition' && r.field === 'state');
        const stateValue = state && state.kind === 'condition' ? String(state.value) : undefined;
        return fetcher({ page: query.page, pageSize: query.pageSize, search: query.search, state: stateValue });
      },
      filterFields: FILTER_FIELDS,
      exportColumns: [],
      actions: [],
      searchPlaceholder: 'Search recipients…',
      enableStatusViews: false,
    };
  }, [fetcher, formatDateTime]);
}
