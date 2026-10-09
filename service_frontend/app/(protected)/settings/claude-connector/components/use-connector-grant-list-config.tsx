'use client';

import { useEffect, useMemo, useState } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Slash } from 'lucide-react';
import { toast } from '@/lib/toast';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { StatusBadge } from '@/components/platform/status-badge';
import {
  DataGridTableRowSelect,
  DataGridTableRowSelectAll,
} from '@/components/ui/data-grid-table';
import { ClampedText } from '@/components/platform/clamped-text';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import type { ResourceAction, ResourceListConfig } from '@/components/platform/resource-list';
import { useDatetime } from '@/hooks/use-datetime';
import { toCsv } from '@/lib/csv';
import {
  bulkRevokeGrants,
  listGrants,
  listProducts,
  revokeGrant,
} from '@/services/connector-service';
import type { FilterFieldDef, FilterGroup, ListQuery } from '@/types/resource';
import type { ConnectorGrant, ConnectorGrantStatus } from '@/types/connector';
import { CONNECTOR_STATUS_REGISTRY, connectorGrantPath } from './connector-status';

export const CONNECTOR_SEGMENTS: { id: ConnectorGrantStatus; label: string }[] = [
  { id: 'active', label: 'Active' },
  { id: 'revoked', label: 'Revoked' },
  { id: 'expired', label: 'Expired' },
];

const stop = (e: React.MouseEvent) => e.stopPropagation();

/** First `eq` / `in[0]` value a filter tree holds for a field (server filters are exact). */
function filterValue(group: FilterGroup | null | undefined, field: string): string | undefined {
  for (const rule of group?.rules ?? []) {
    if (rule.kind === 'group') {
      const nested = filterValue(rule, field);
      if (nested !== undefined) return nested;
    } else if (rule.field === field) {
      const v = rule.value;
      if (typeof v === 'string' && v) return v;
      if (Array.isArray(v) && v.length) return v[0];
    }
  }
  return undefined;
}

function grantQuery(query: ListQuery) {
  return {
    status:
      (filterValue(query.filter, 'status') as ConnectorGrantStatus | undefined) ??
      (query.segment as ConnectorGrantStatus | undefined) ??
      'active',
    product: filterValue(query.filter, 'product'),
    search: query.search || undefined,
  };
}

const EXPORT_COLUMNS = [
  { id: 'userName', label: 'User' },
  { id: 'productUserId', label: 'Product user id' },
  { id: 'productName', label: 'Product' },
  { id: 'clientName', label: 'Client' },
  { id: 'grantedAt', label: 'Granted' },
  { id: 'lastUsedAt', label: 'Last used' },
  { id: 'calls30d', label: 'Calls (30 d)' },
  { id: 'status', label: 'Status' },
];

/** Revoke registry - row + form (plain confirm) and bulk (typed REVOKE). */
export function useConnectorGrantActions(): ResourceAction<ConnectorGrant>[] {
  return useMemo<ResourceAction<ConnectorGrant>[]>(
    () => [
      {
        id: 'revoke',
        label: 'Revoke',
        icon: Slash,
        tone: 'destructive',
        surfaces: { row: true, form: true },
        permission: 'connector.manage',
        isVisible: (rows) => rows.every((r) => r.status === 'active'),
        confirm: {
          title: 'Revoke this grant?',
          description: (rows) =>
            `${rows[0]?.userName} loses Claude access to ${rows[0]?.productName} now. Connecting again asks them to sign in to ${rows[0]?.productName}.`,
          confirmLabel: 'Revoke',
        },
        run: async (rows, runtime) => {
          for (const row of rows) await revokeGrant(row.id);
          toast.success('Access revoked.');
          runtime.reload();
        },
      },
      {
        id: 'revoke-bulk',
        label: 'Revoke',
        icon: Slash,
        tone: 'destructive',
        surfaces: { bulk: true },
        permission: 'connector.manage',
        isVisible: (rows) => rows.every((r) => r.status === 'active'),
        confirm: {
          title: (rows) => `Revoke ${rows.length} grants?`,
          description: (rows) =>
            `These ${rows.length} users lose Claude access to ${rows[0]?.productName} now.`,
          confirmLabel: (rows) => `Revoke ${rows.length}`,
          input: {
            expected: () => 'REVOKE',
            hint: () => 'Type REVOKE to confirm.',
          },
        },
        run: async (rows, runtime) => {
          const result = await bulkRevokeGrants(rows.map((r) => r.id));
          toast.success(`Revoked ${result.revoked} grant(s).`);
          runtime.reload();
        },
      },
    ],
    [],
  );
}

export function useConnectorGrantListConfig(): ResourceListConfig<ConnectorGrant> {
  const actions = useConnectorGrantActions();
  const { formatDateTime } = useDatetime();
  const [productOptions, setProductOptions] = useState<{ label: string; value: string }[]>([]);
  useEffect(() => {
    let cancelled = false;
    Promise.resolve()
      .then(() => listProducts())
      .then((ps) => {
        if (!cancelled) {
          setProductOptions(ps.map((p) => ({ label: p.displayName ?? p.key, value: p.key })));
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);
  const filterFields = useMemo<FilterFieldDef[]>(
    () => [
      {
        field: 'status',
        label: 'Status',
        type: 'enum',
        options: CONNECTOR_SEGMENTS.map((s) => ({ label: s.label, value: s.id })),
      },
      { field: 'product', label: 'Product', type: 'enum', options: productOptions },
    ],
    [productOptions],
  );

  return useMemo<ResourceListConfig<ConnectorGrant>>(
    () => ({
      viewKey: 'claude-connector-grants',
      getRowId: (row) => row.id,
      rowHref: (row) => connectorGrantPath(row.id),
      fetcher: (query) =>
        listGrants({ ...grantQuery(query), page: query.page, pageSize: query.pageSize }),
      exporter: async (query, columns, ids) => {
        const rows: ConnectorGrant[] = [];
        for (let page = 0; ; page += 1) {
          const res = await listGrants({ ...grantQuery(query), page, pageSize: 200 });
          rows.push(...res.data);
          if (rows.length >= res.total || res.data.length === 0) break;
        }
        const wanted = ids ? rows.filter((r) => ids.includes(r.id)) : rows;
        const cols = EXPORT_COLUMNS.filter((c) => columns.includes(c.id));
        return toCsv(
          cols.map((c) => c.label),
          wanted.map((r) => cols.map((c) => r[c.id as keyof ConnectorGrant] as string | number | null)),
        );
      },
      exportFilename: 'claude-connector-grants',
      searchPlaceholder: 'Search user or product user id',
      segments: CONNECTOR_SEGMENTS,
      defaultSegment: 'active',
      defaultView: 'list',
      columns: [
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
          id: 'userName',
          accessorFn: (row) => row.userName,
          meta: { headerTitle: 'User' },
          header: ({ column }) => <DataGridColumnHeader title="User" column={column} />,
          cell: ({ row }) => (
            <span className="font-medium text-foreground">{row.original.userName}</span>
          ),
          size: 180,
          enableSorting: false,
        },
        {
          id: 'productUserId',
          accessorFn: (row) => row.productUserId,
          meta: { headerTitle: 'Product user id' },
          header: ({ column }) => <DataGridColumnHeader title="Product user id" column={column} />,
          cell: ({ row }) => (
            <code className="text-xs text-muted-foreground">{row.original.productUserId}</code>
          ),
          size: 140,
          enableSorting: false,
        },
        {
          id: 'product',
          accessorFn: (row) => row.productName,
          meta: { headerTitle: 'Product' },
          header: ({ column }) => <DataGridColumnHeader title="Product" column={column} />,
          cell: ({ row }) => <ClampedText text={row.original.productName} lines={1} />,
          size: 120,
          enableSorting: false,
        },
        {
          id: 'clientName',
          accessorFn: (row) => row.clientName,
          meta: { headerTitle: 'Client' },
          header: ({ column }) => <DataGridColumnHeader title="Client" column={column} />,
          cell: ({ row }) => <ClampedText text={row.original.clientName} lines={1} />,
          size: 120,
          enableSorting: false,
        },
        {
          id: 'grantedAt',
          accessorFn: (row) => row.grantedAt,
          meta: { headerTitle: 'Granted' },
          header: ({ column }) => <DataGridColumnHeader title="Granted" column={column} />,
          cell: ({ row }) => (
            <span className="text-sm text-muted-foreground">
              {formatDateTime(row.original.grantedAt)}
            </span>
          ),
          size: 160,
          enableSorting: false,
        },
        {
          id: 'lastUsedAt',
          accessorFn: (row) => row.lastUsedAt,
          meta: { headerTitle: 'Last used' },
          header: ({ column }) => <DataGridColumnHeader title="Last used" column={column} />,
          cell: ({ row }) => (
            <span className="text-sm text-muted-foreground">
              {row.original.lastUsedAt ? formatDateTime(row.original.lastUsedAt) : '-'}
            </span>
          ),
          size: 160,
          enableSorting: false,
        },
        {
          id: 'calls30d',
          accessorFn: (row) => row.calls30d,
          meta: { headerTitle: 'Calls (30 d)' },
          header: ({ column }) => <DataGridColumnHeader title="Calls (30 d)" column={column} />,
          cell: ({ row }) => (
            <span className="text-sm text-muted-foreground">{row.original.calls30d}</span>
          ),
          size: 110,
          enableSorting: false,
        },
        {
          id: 'status',
          accessorFn: (row) => row.status,
          meta: { headerTitle: 'Status' },
          header: ({ column }) => <DataGridColumnHeader title="Status" column={column} />,
          cell: ({ row }) => (
            <StatusBadge
              status={row.original.status}
              registry={CONNECTOR_STATUS_REGISTRY}
              size="sm"
            />
          ),
          size: 110,
          enableSorting: false,
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
      ] as ColumnDef<ConnectorGrant>[],
      cardRender: (row) => (
        <div className="flex flex-col gap-2">
          <div className="flex items-start justify-between gap-2">
            <span className="font-medium text-foreground">{row.userName}</span>
            <StatusBadge status={row.status} registry={CONNECTOR_STATUS_REGISTRY} size="sm" />
          </div>
          <span className="text-sm text-muted-foreground">{row.productName}</span>
          <span className="text-xs text-muted-foreground">
            {row.clientName} · {row.calls30d} calls
          </span>
        </div>
      ),
      filterFields,
      exportColumns: EXPORT_COLUMNS,
      actions,
    }),
    [actions, formatDateTime, filterFields],
  );
}
