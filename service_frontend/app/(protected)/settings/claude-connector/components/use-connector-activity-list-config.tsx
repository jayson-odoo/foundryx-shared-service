'use client';

import { useMemo } from 'react';
import type { Column, ColumnDef } from '@tanstack/react-table';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { Badge } from '@/components/ui/badge';
import { ClampedText } from '@/components/platform/clamped-text';
import type { ResourceListConfig } from '@/components/platform/resource-list';
import { useDatetime } from '@/hooks/use-datetime';
import type { ConnectorActivity, ConnectorActivityRow } from '@/types/connector';

const EVENT_LABELS: Record<string, string> = {
  consented: 'Consented',
  denied: 'Denied',
  refreshed: 'Token refreshed',
  revoked: 'Revoked',
  revoked_by_admin: 'Revoked by admin',
  refresh_reuse: 'Refresh token reused',
  expired: 'Expired',
};

function eventLabel(type: string): string {
  return EVENT_LABELS[type] ?? type.replaceAll('_', ' ');
}

/** Calls + lifecycle events merged into one newest-first table. */
export function mergeActivity(activity: ConnectorActivity | null): ConnectorActivityRow[] {
  const calls: ConnectorActivityRow[] = (activity?.calls ?? []).map((c) => ({
    id: `call:${c.id}`,
    kind: 'call',
    at: c.at,
    event: 'Tool call',
    tool: c.tool,
    status: c.errorCode || 'ok',
    rows: c.rows,
    chars: c.chars,
    ms: c.ms,
    args: c.args ?? null,
    truncated: c.truncated,
  }));
  const events: ConnectorActivityRow[] = (activity?.events ?? []).map((e) => ({
    id: `event:${e.id}`,
    kind: 'event',
    at: e.at,
    event: eventLabel(e.type),
    tool: null,
    status: null,
    rows: null,
    chars: null,
    ms: null,
    args: e.detail ?? null,
    truncated: false,
  }));
  return [...calls, ...events].sort((a, b) => Date.parse(b.at) - Date.parse(a.at));
}

const dash = (v: string | number | null | undefined) => (v === null || v === undefined || v === '' ? '-' : String(v));

type Header = { column: Column<ConnectorActivityRow> };

function col(
  id: string,
  title: string,
  size: number,
  cell: ColumnDef<ConnectorActivityRow>['cell'],
): ColumnDef<ConnectorActivityRow> {
  return {
    id,
    meta: { headerTitle: title },
    header: ({ column }: Header) => <DataGridColumnHeader title={title} column={column} />,
    cell,
    size,
    enableSorting: false,
  };
}

/** Activity on the Resource shell: one client-paged table, no title/toggle chrome. */
export function useConnectorActivityListConfig(
  activity: ConnectorActivity | null,
): ResourceListConfig<ConnectorActivityRow> {
  const { formatDateTime } = useDatetime();
  const merged = useMemo(() => mergeActivity(activity), [activity]);
  return useMemo<ResourceListConfig<ConnectorActivityRow>>(
    () => ({
      viewKey: 'claude-connector-activity',
      getRowId: (row) => row.id,
      rowHref: () => '#',
      fetcher: async (query) => {
        const start = query.page * query.pageSize;
        return {
          data: merged.slice(start, start + query.pageSize),
          total: merged.length,
          page: query.page,
        };
      },
      defaultView: 'list',
      enableStatusViews: false,
      columns: [
        col('at', 'Time', 170, ({ row }) => (
          <span className="text-sm text-muted-foreground">{formatDateTime(row.original.at)}</span>
        )),
        col('event', 'Event', 140, ({ row }) => <span className="text-sm">{row.original.event}</span>),
        col('tool', 'Tool', 200, ({ row }) => (
          <code className="text-xs">{dash(row.original.tool)}</code>
        )),
        col('status', 'Status', 190, ({ row }) => (
          <span className="text-sm">{dash(row.original.status)}</span>
        )),
        col('rows', 'Rows', 80, ({ row }) => <span className="text-sm">{dash(row.original.rows)}</span>),
        col('chars', 'Chars', 90, ({ row }) => <span className="text-sm">{dash(row.original.chars)}</span>),
        col('ms', 'ms', 80, ({ row }) => <span className="text-sm">{dash(row.original.ms)}</span>),
        col('args', 'Args', 260, ({ row }) => (
          <div className="flex items-center gap-2">
            {row.original.args ? (
              <ClampedText text={row.original.args} lines={1} />
            ) : (
              <span className="text-sm">-</span>
            )}
            {row.original.truncated && (
              <Badge variant="warning" appearance="light" size="sm">
                Truncated
              </Badge>
            )}
          </div>
        )),
      ],
      filterFields: [],
      exportColumns: [],
      actions: [],
    }),
    [merged, formatDateTime],
  );
}
