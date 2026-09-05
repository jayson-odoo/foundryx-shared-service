'use client';

import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Pencil, RefreshCw, Play, Pause, ListChecks, Trash2, Webhook } from 'lucide-react';
import { toast } from 'sonner';
import { Badge } from '@/components/ui/badge';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { StatusBadge } from '@/components/platform/status-badge';
import { ClampedText } from '@/components/platform/clamped-text';
import { OverflowPills } from '@/components/platform/overflow-pills';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import type { ResourceListConfig, ResourceAction } from '@/components/platform/resource-list';
import type { ListQuery, ListResult, FilterGroup, FilterRule } from '@/types/resource';
import { useDatetime } from '@/hooks/use-datetime';
import { whatsappWebhookService } from '@/services/whatsapp-webhook-service';
import type { WebhookEndpoint } from '@/types/whatsapp-webhook';
import { toCsv } from '@/lib/csv';
import {
  WEBHOOK_STATUS_REGISTRY,
  WEBHOOK_STATUS_OPTIONS,
  eventLabel,
} from './webhook-status';

const stop = (e: React.MouseEvent) => e.stopPropagation();

/** Endpoint-list action callbacks the tab wires to its dialogs. */
export interface WebhookListCallbacks {
  onCreate: () => void;
  onEdit: (endpoint: WebhookEndpoint) => void;
  onRotate: (endpoint: WebhookEndpoint) => void;
  onViewDeliveries: (endpoint: WebhookEndpoint) => void;
}

/** Walk the (small) endpoint list client-side for the declared filter fields. */
function matchesFilter(item: WebhookEndpoint, group: FilterGroup | null | undefined): boolean {
  if (!group || group.rules.length === 0) return true;
  const test = (rule: FilterRule): boolean => {
    if (rule.kind === 'group') {
      const results = rule.rules.map(test);
      return rule.combinator === 'or' ? results.some(Boolean) : results.every(Boolean);
    }
    const v = String(rule.value ?? '').toUpperCase();
    if (rule.field === 'status') {
      if (rule.operator === 'neq') return item.status !== v;
      return item.status === v;
    }
    return true;
  };
  const results = group.rules.map(test);
  return group.combinator === 'or' ? results.some(Boolean) : results.every(Boolean);
}

function sortItems(rows: WebhookEndpoint[], sort: ListQuery['sort']): WebhookEndpoint[] {
  if (!sort) return rows;
  const val = (i: WebhookEndpoint): string => {
    switch (sort.id) {
      case 'name':
        return i.name;
      case 'url':
        return i.url;
      case 'status':
        return i.status;
      case 'lastSuccess':
        return i.lastSuccessAt ?? '';
      default:
        return '';
    }
  };
  const sorted = [...rows].sort((a, b) => val(a).localeCompare(val(b)));
  return sort.desc ? sorted.reverse() : sorted;
}

export interface UseWebhookListResult {
  config: ResourceListConfig<WebhookEndpoint>;
}

/**
 * Channel consumer-webhook list config (omnichannel Slice 4) - endpoints on the
 * full Resource shell embedded in the channel detail's Webhooks tab. The set per
 * channel is small, so the fetcher pulls it whole and applies
 * search/filter/sort/paginate client-side (mirrors the API-keys tab). No detail
 * page (`rowHref` '#'); Add = the create action, the rest are row actions.
 */
export function useWebhookList(
  channelId: string,
  callbacks: WebhookListCallbacks,
): UseWebhookListResult {
  const { formatDateTime } = useDatetime();
  const { onCreate, onEdit, onRotate, onViewDeliveries } = callbacks;

  const actions = useMemo<ResourceAction<WebhookEndpoint>[]>(
    () => [
      {
        id: 'edit',
        label: 'Edit',
        icon: Pencil,
        permission: 'webhooks.manage',
        surfaces: { row: true },
        isVisible: (rows) => rows.length === 1,
        run: (rows) => rows[0] && onEdit(rows[0]),
      },
      {
        id: 'rotate',
        label: 'Rotate secret',
        icon: RefreshCw,
        permission: 'webhooks.manage',
        surfaces: { row: true },
        isVisible: (rows) => rows.length === 1,
        run: (rows) => rows[0] && onRotate(rows[0]),
      },
      {
        id: 'enable',
        label: 'Enable',
        icon: Play,
        permission: 'webhooks.manage',
        surfaces: { row: true },
        isVisible: (rows) => rows.length === 1 && rows[0]?.status !== 'ACTIVE',
        run: async (rows, rt) => {
          const [e] = rows;
          if (!e) return;
          try {
            await whatsappWebhookService.enable(e.id);
            toast.success('Endpoint enabled.');
            rt.reload();
          } catch {
            toast.error('Could not enable the endpoint. Please retry.');
          }
        },
      },
      {
        id: 'disable',
        label: 'Disable',
        icon: Pause,
        permission: 'webhooks.manage',
        surfaces: { row: true },
        isVisible: (rows) => rows.length === 1 && rows[0]?.status === 'ACTIVE',
        // Grace-window deferred action (sprint-4/23, T5 fix round 1, item
        // 15) - no confirm, no `run` (the registered `webhooks.set_active`
        // handler commits it server-side); `payload.active=false` is the
        // Disable direction (the Enable action above stays a plain, no-
        // confirm run - it was never gated to begin with).
        deferred: {
          actionKey: 'webhooks.set_active',
          entityType: 'webhook_endpoint',
          payload: () => ({ active: false }),
        },
      },
      {
        id: 'deliveries',
        label: 'View deliveries',
        icon: ListChecks,
        permission: 'webhooks.read',
        surfaces: { row: true },
        isVisible: (rows) => rows.length === 1,
        run: (rows) => rows[0] && onViewDeliveries(rows[0]),
      },
      {
        id: 'delete',
        label: 'Delete',
        icon: Trash2,
        tone: 'destructive',
        permission: 'webhooks.manage',
        surfaces: { row: true },
        isVisible: (rows) => rows.length === 1,
        // Grace-window deferred action - no confirm, no `run` (the
        // registered `webhooks.delete` handler commits it server-side).
        deferred: { actionKey: 'webhooks.delete', entityType: 'webhook_endpoint' },
      },
    ],
    [onEdit, onRotate, onViewDeliveries],
  );

  const config = useMemo<ResourceListConfig<WebhookEndpoint>>(() => {
    const columns: ColumnDef<WebhookEndpoint>[] = [
      {
        id: 'name',
        accessorFn: (r) => r.name,
        meta: { headerTitle: 'Name' },
        header: ({ column }) => <DataGridColumnHeader title="Name" column={column} />,
        cell: ({ row }) => (
          <div className="flex items-center gap-2">
            <Webhook className="size-4 shrink-0 text-muted-foreground" />
            <ClampedText text={row.original.name} lines={1} className="font-medium" />
          </div>
        ),
        size: 180,
        enableSorting: true,
      },
      {
        id: 'url',
        accessorFn: (r) => r.url,
        meta: { headerTitle: 'URL' },
        header: ({ column }) => <DataGridColumnHeader title="URL" column={column} />,
        cell: ({ row }) => (
          <ClampedText
            text={row.original.url}
            lines={1}
            className="font-mono text-xs text-muted-foreground"
          />
        ),
        size: 240,
        enableSorting: true,
      },
      {
        id: 'events',
        accessorFn: (r) => r.events.join(','),
        meta: { headerTitle: 'Events' },
        header: () => <span>Events</span>,
        cell: ({ row }) => (
          <OverflowPills
            items={row.original.events}
            keyFor={(e) => e}
            renderPill={(e) => (
              <Badge variant="secondary" appearance="light" size="sm">
                {eventLabel(e)}
              </Badge>
            )}
          />
        ),
        size: 220,
        enableSorting: false,
      },
      {
        id: 'status',
        accessorFn: (r) => r.status,
        meta: { headerTitle: 'Status' },
        header: ({ column }) => <DataGridColumnHeader title="Status" column={column} />,
        cell: ({ row }) => {
          const e = row.original;
          return (
            <div className="flex flex-col items-start gap-1">
              <StatusBadge status={e.status} registry={WEBHOOK_STATUS_REGISTRY} />
              {e.consecutiveFailures > 0 && (
                <span className="text-xs text-muted-foreground">
                  {e.consecutiveFailures} consecutive failures
                </span>
              )}
              {e.status === 'AUTO_DISABLED' && e.disabledReason && (
                <ClampedText
                  text={e.disabledReason}
                  lines={2}
                  className="text-xs text-destructive"
                />
              )}
            </div>
          );
        },
        size: 180,
        enableSorting: true,
      },
      {
        id: 'lastSuccess',
        accessorFn: (r) => r.lastSuccessAt,
        meta: { headerTitle: 'Last success' },
        header: ({ column }) => <DataGridColumnHeader title="Last success" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">
            {row.original.lastSuccessAt ? formatDateTime(row.original.lastSuccessAt) : 'Never'}
          </span>
        ),
        size: 180,
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

    const fetcher = async (query: ListQuery): Promise<ListResult<WebhookEndpoint>> => {
      const all = await whatsappWebhookService.list(channelId);
      let rows = all;
      const search = query.search?.trim().toLowerCase();
      if (search) {
        rows = rows.filter(
          (r) =>
            r.name.toLowerCase().includes(search) || r.url.toLowerCase().includes(search),
        );
      }
      rows = rows.filter((r) => matchesFilter(r, query.filter));
      rows = sortItems(rows, query.sort);
      const total = rows.length;
      const start = query.page * query.pageSize;
      return { data: rows.slice(start, start + query.pageSize), total, page: query.page };
    };

    const exporter = async (query: ListQuery): Promise<string> => {
      const { data } = await fetcher({ ...query, page: 0, pageSize: 10_000 });
      return toCsv(
        ['Name', 'URL', 'Events', 'Status', 'Consecutive failures', 'Last success'],
        data.map((r) => [
          r.name,
          r.url,
          r.events.map(eventLabel).join('; '),
          r.status,
          String(r.consecutiveFailures),
          r.lastSuccessAt ?? '',
        ]),
      );
    };

    return {
      viewKey: `omnichannel.webhooks.${channelId}`,
      columns,
      getRowId: (e) => e.id,
      rowHref: () => '#', // no detail page
      fetcher,
      exporter,
      filterFields: [
        { field: 'status', label: 'Status', type: 'enum', options: WEBHOOK_STATUS_OPTIONS },
      ],
      exportColumns: [
        { id: 'name', label: 'Name' },
        { id: 'url', label: 'URL' },
        { id: 'events', label: 'Events' },
        { id: 'status', label: 'Status' },
        { id: 'lastSuccess', label: 'Last success' },
      ],
      actions,
      searchPlaceholder: 'Search endpoints…',
      searchHints: ['Name', 'URL'],
      defaultSort: { id: 'name', desc: false },
      exportFilename: 'webhook-endpoints',
      enableStatusViews: false,
      createLabel: 'Add endpoint',
      createPermission: 'webhooks.manage',
      onCreate,
    };
  }, [channelId, actions, onCreate, formatDateTime]);

  return { config };
}
