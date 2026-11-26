'use client';

import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Send } from 'lucide-react';
import { toast } from '@/lib/toast';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { ClampedText } from '@/components/platform/clamped-text';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import { embeddedListConfig } from '@/components/platform/resource-list/embedded-list-config';
import type { ResourceAction, ResourceListConfig } from '@/components/platform/resource-list';
import { StatusBadge } from '@/components/platform/status-badge';
import { hubConnectorErrorMessage } from '@/hooks/use-hub-connector';
import { useDatetime } from '@/hooks/use-datetime';
import { hubConnectorService } from '@/services/hub-connector-service';
import type { HubDelivery } from '@/types/hub-connector';
import type { ListQuery, ListResult } from '@/types/resource';
import { DELIVERY_STATUS_REGISTRY, HUB_MANAGE } from '../../components/hub-meta';

const stop = (e: React.MouseEvent) => e.stopPropagation();

const EVENT_LABELS: Record<string, string> = {
  'availability.updated': 'Availability update',
};

/** The receiver's answer in plain words (never the raw technical error). */
export function deliveryResult(d: HubDelivery): string {
  if (d.status === 'SUCCESS') return 'Delivered';
  if (d.lastCode) return `Receiver answered ${d.lastCode}`;
  if (d.lastError) return 'Receiver could not be reached';
  return '-';
}

/** The hub's delivery log (embedded list in the Deliveries tab). */
export function useDeliveriesListConfig(hubId: string): ResourceListConfig<HubDelivery> {
  const { formatDmyDateTime } = useDatetime();

  return useMemo<ResourceListConfig<HubDelivery>>(() => {
    const actions: ResourceAction<HubDelivery>[] = [
      {
        id: 'send-again',
        label: 'Send again',
        icon: Send,
        permission: HUB_MANAGE,
        surfaces: { row: true },
        isVisible: (rows) => rows.length === 1 && rows[0].status === 'FAILED',
        run: async (rows, runtime) => {
          try {
            await hubConnectorService.redeliver(rows[0].id);
            toast.success('Queued to send again.');
            runtime.reload();
          } catch (err) {
            toast.error(hubConnectorErrorMessage(err, 'Could not send it again. Please try again.'));
          }
        },
      },
    ];

    const columns: ColumnDef<HubDelivery>[] = [
      {
        id: 'createdAt',
        accessorFn: (r) => r.createdAt,
        meta: { headerTitle: 'Time' },
        header: ({ column }) => <DataGridColumnHeader title="Time" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">{formatDmyDateTime(row.original.createdAt)}</span>
        ),
        size: 170,
        enableSorting: true,
      },
      {
        id: 'customerName',
        accessorFn: (r) => r.customerName,
        meta: { headerTitle: 'Customer' },
        header: ({ column }) => <DataGridColumnHeader title="Customer" column={column} />,
        cell: ({ row }) => <ClampedText text={row.original.customerName} lines={1} className="font-medium" />,
        size: 200,
        enableSorting: true,
      },
      {
        id: 'event',
        accessorFn: (r) => r.event,
        meta: { headerTitle: 'Event' },
        header: ({ column }) => <DataGridColumnHeader title="Event" column={column} />,
        cell: ({ row }) => (
          <ClampedText text={EVENT_LABELS[row.original.event] ?? row.original.event} lines={1} className="text-sm" />
        ),
        size: 170,
        enableSorting: true,
      },
      {
        id: 'status',
        accessorFn: (r) => r.status,
        meta: { headerTitle: 'Status' },
        header: ({ column }) => <DataGridColumnHeader title="Status" column={column} />,
        cell: ({ row }) => (
          <div className="flex items-start">
            <StatusBadge status={row.original.status} registry={DELIVERY_STATUS_REGISTRY} />
          </div>
        ),
        size: 120,
        enableSorting: true,
      },
      {
        id: 'attempt',
        accessorFn: (r) => r.attempt,
        meta: { headerTitle: 'Attempts' },
        header: ({ column }) => <DataGridColumnHeader title="Attempts" column={column} />,
        cell: ({ row }) => <span className="text-sm">{row.original.attempt}</span>,
        size: 100,
        enableSorting: true,
      },
      {
        id: 'result',
        accessorFn: (r) => deliveryResult(r),
        meta: { headerTitle: 'Result' },
        header: ({ column }) => <DataGridColumnHeader title="Result" column={column} />,
        cell: ({ row }) => (
          <ClampedText text={deliveryResult(row.original)} lines={1} className="text-sm text-muted-foreground" />
        ),
        size: 240,
        enableSorting: false,
      },
      {
        id: 'actions',
        meta: { reorderable: false },
        header: () => null,
        cell: ({ row, table }) => {
          const meta = table.options.meta;
          return (
            <div onClick={stop} className="flex justify-end">
              <ActionMenu
                actions={actions}
                rows={[row.original]}
                runtime={{
                  ctx: meta?.resourceCtx,
                  index: (meta?.pageStartIndex ?? 0) + row.index,
                  reload: meta?.reload ?? (() => {}),
                }}
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

    const fetcher = async (query: ListQuery): Promise<ListResult<HubDelivery>> => {
      const res = await hubConnectorService.listDeliveries(hubId, query);
      return { data: res.data, total: res.total, page: query.page };
    };

    return {
      // A delivery log has no trash: no Active | Trashed switch.
      enableStatusViews: false,
      ...embeddedListConfig<HubDelivery>({
        viewKey: 'hub-connector.deliveries',
        columns,
        fetcher,
        getRowId: (r) => r.id,
        rowHref: () => '#',
        searchPlaceholder: 'Search deliveries…',
        defaultSort: { id: 'createdAt', desc: true },
        actions,
      }),
    };
  }, [formatDmyDateTime, hubId]);
}
