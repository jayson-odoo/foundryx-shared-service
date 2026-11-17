'use client';

import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Send, Trash2 } from 'lucide-react';
import { toast } from '@/lib/toast';
import { Badge } from '@/components/ui/badge';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { ClampedText } from '@/components/platform/clamped-text';
import { OverflowPills } from '@/components/platform/overflow-pills';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import type { ResourceAction, ResourceListConfig } from '@/components/platform/resource-list';
import type { ListQuery, ListResult } from '@/types/resource';
import { LEAD_EVENT_LABELS, type LeadEvent, type LeadReceiverItem } from '@/types/lead-capture';
import { useDatetime } from '@/hooks/use-datetime';
import { leadCaptureErrorMessage, useSendTestPush } from '@/hooks/use-lead-capture';
import { applyClientQuery, type ClientListSpec } from '@/lib/client-list-query';
import { toCsv } from '@/lib/csv';
import { leadCaptureService } from '@/services/lead-capture-service';

const MANAGE = 'lead_capture.manage';

const eventLabels = (events: LeadEvent[]) => events.map((e) => LEAD_EVENT_LABELS[e] ?? e);

const spec: ClientListSpec<LeadReceiverItem> = {
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
 * The product's receivers (lane L-D, AC-64-57) on the Resource shell. Row
 * actions: Send test push (one signed sample lead to that receiver) and Remove
 * (grace-window `lead_capture_receivers.remove`). Create opens the add dialog.
 */
export function useReceiverList(
  onCreate: () => void,
  onChanged: () => void,
): ResourceListConfig<LeadReceiverItem> {
  const { formatDmyDateTime } = useDatetime();
  const sendTestPush = useSendTestPush();

  const actions = useMemo<ResourceAction<LeadReceiverItem>[]>(
    () => [
      {
        id: 'test-push',
        label: 'Send test push',
        icon: Send,
        permission: MANAGE,
        surfaces: { row: true },
        isVisible: (rows) => rows.length === 1,
        run: async (rows, runtime) => {
          const [receiver] = rows;
          if (!receiver) return;
          try {
            await sendTestPush(receiver.id);
            toast.success('Test push sent.');
          } catch (err) {
            toast.error(leadCaptureErrorMessage(err, 'Could not send the test push. Please try again.'));
          }
          runtime.reload();
        },
      },
      {
        id: 'remove',
        label: 'Remove',
        icon: Trash2,
        tone: 'destructive',
        permission: MANAGE,
        surfaces: { row: true },
        isVisible: (rows) => rows.length === 1,
        deferred: { actionKey: 'lead_capture_receivers.remove', entityType: 'lead_capture_receiver' },
      },
    ],
    [sendTestPush],
  );

  return useMemo<ResourceListConfig<LeadReceiverItem>>(() => {
    const columns: ColumnDef<LeadReceiverItem>[] = [
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

    const fetcher = async (query: ListQuery): Promise<ListResult<LeadReceiverItem>> =>
      applyClientQuery(await leadCaptureService.listReceivers(), query, spec);

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
      viewKey: 'lead-capture.receivers',
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
          options: (Object.keys(LEAD_EVENT_LABELS) as LeadEvent[]).map((value) => ({
            value,
            label: LEAD_EVENT_LABELS[value],
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
      exportFilename: 'lead-capture-receivers',
      enableStatusViews: false,
      urlState: true,
      createLabel: 'Create',
      createPermission: MANAGE,
      onCreate,
      // The right-click / long-press menu (#253) reloads only the list; the
      // page's Push / Pull only state follows the receivers too.
      onDeferredCommitted: () => onChanged(),
    };
  }, [actions, formatDmyDateTime, onCreate, onChanged]);
}
