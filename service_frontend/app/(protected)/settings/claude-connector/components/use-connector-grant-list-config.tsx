'use client';

import { useMemo } from 'react';
import { Slash } from 'lucide-react';
import { toast } from '@/lib/toast';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { StatusBadge } from '@/components/platform/status-badge';
import { ClampedText } from '@/components/platform/clamped-text';
import type { ResourceAction, ResourceListConfig } from '@/components/platform/resource-list';
import { useDatetime } from '@/hooks/use-datetime';
import { bulkRevokeGrants, listGrants, revokeGrant } from '@/services/connector-service';
import type { ConnectorGrant, ConnectorGrantStatus } from '@/types/connector';
import { CONNECTOR_STATUS_REGISTRY, connectorGrantPath } from './connector-status';

export const CONNECTOR_SEGMENTS: { id: ConnectorGrantStatus; label: string }[] = [
  { id: 'active', label: 'Active' },
  { id: 'revoked', label: 'Revoked' },
  { id: 'expired', label: 'Expired' },
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
          title: 'Revoke access?',
          description: 'Claude loses access for this user immediately.',
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
          title: 'Revoke access?',
          description: 'Claude loses access for the selected users immediately.',
          confirmLabel: 'Revoke',
          input: {
            expected: () => 'REVOKE',
            hint: () => 'Type REVOKE to confirm',
          },
        },
        run: async (rows, runtime) => {
          await bulkRevokeGrants(rows.map((r) => r.id));
          toast.success(`Revoked ${rows.length} grant(s).`);
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

  return useMemo<ResourceListConfig<ConnectorGrant>>(
    () => ({
      viewKey: 'claude-connector-grants',
      getRowId: (row) => row.id,
      rowHref: (row) => connectorGrantPath(row.id),
      fetcher: (query) =>
        listGrants({
          status: (query.segment as ConnectorGrantStatus | undefined) ?? 'active',
          search: query.search || undefined,
          page: query.page,
          pageSize: query.pageSize,
        }),
      searchPlaceholder: 'Search user or product user id',
      segments: CONNECTOR_SEGMENTS,
      defaultSegment: 'active',
      defaultView: 'list',
      columns: [
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
          accessorFn: (row) => row.product,
          meta: { headerTitle: 'Product' },
          header: ({ column }) => <DataGridColumnHeader title="Product" column={column} />,
          cell: ({ row }) => <ClampedText text={row.original.product} lines={1} />,
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
      ],
      cardRender: (row) => (
        <div className="flex flex-col gap-2">
          <div className="flex items-start justify-between gap-2">
            <span className="font-medium text-foreground">{row.userName}</span>
            <StatusBadge status={row.status} registry={CONNECTOR_STATUS_REGISTRY} size="sm" />
          </div>
          <span className="text-sm text-muted-foreground">{row.product}</span>
          <span className="text-xs text-muted-foreground">
            {row.clientName} · {row.calls30d} calls
          </span>
        </div>
      ),
      filterFields: [],
      exportColumns: [],
      actions,
    }),
    [actions, formatDateTime],
  );
}
