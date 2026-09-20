'use client';

import { useMemo, useState } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { Badge } from '@/components/ui/badge';
import { ClampedText } from '@/components/platform/clamped-text';
import { OverflowPills } from '@/components/platform/overflow-pills';
import { StatusBadge } from '@/components/platform/status-badge';
import type { ResourceListConfig } from '@/components/platform/resource-list';
import { useDatetime } from '@/hooks/use-datetime';
import { autocountService } from '@/services/autocount-service';
import type { AutocountCompany, AutocountPullSnapshotStatus } from '@/types/autocount';
import type { ListQuery, ListResult } from '@/types/resource';
import {
  AC_PULL_KEY_STATUS_REGISTRY,
  AC_PULL_MANAGE,
  AC_PULL_SNAPSHOT_STATUS_REGISTRY,
  acPullSnapshotHref,
  entityLabel,
  pullEntityFromWire,
} from '../../components/autocount-meta';
import { type AutocountPullListRow, pullRowId } from './pull-row';

export interface UsePullListConfigOptions {
  companies: AutocountCompany[];
  onIssueKey: () => void;
  onBuildSnapshot: () => void;
}

function companyName(companies: AutocountCompany[], id: string): string {
  return companies.find((c) => c.id === id)?.name ?? id;
}

/**
 * `/autocount/pull` (AC-10-38) - ONE `ResourceList`, Keys | Snapshots as an
 * N-way segment (rendered as a `SearchSelect` by the shell). Columns/actions
 * differ entirely by segment; `activeSegment` is a side-channel the fetcher
 * itself reports (the shell owns segment SELECTION internally, but never
 * exposes it to the config as a prop) - the same "additive side channel"
 * shape `onFilterChange` already uses elsewhere.
 */
export function useAutocountPullListConfig({
  companies,
  onIssueKey,
  onBuildSnapshot,
}: UsePullListConfigOptions): ResourceListConfig<AutocountPullListRow> {
  const { formatDateTime } = useDatetime();
  const [activeSegment, setActiveSegment] = useState<'keys' | 'snapshots'>('keys');

  return useMemo<ResourceListConfig<AutocountPullListRow>>(() => {
    const keyColumns: ColumnDef<AutocountPullListRow>[] = [
      {
        id: 'name',
        accessorFn: (row) => (row.kind === 'key' ? row.name : ''),
        meta: { headerTitle: 'Name', reorderable: false },
        header: ({ column }) => <DataGridColumnHeader title="Name" column={column} />,
        cell: ({ row }) =>
          row.original.kind === 'key' ? (
            <div className="flex min-w-0 flex-col gap-0.5">
              <span className="text-sm font-medium text-foreground">{row.original.name}</span>
              <code className="text-xs text-muted-foreground">{row.original.keyPrefix}...</code>
            </div>
          ) : null,
        size: 220,
        enableSorting: false,
      },
      {
        id: 'companies',
        meta: { headerTitle: 'Companies' },
        header: ({ column }) => <DataGridColumnHeader title="Companies" column={column} />,
        cell: ({ row }) =>
          row.original.kind === 'key' ? (
            <OverflowPills
              items={row.original.companyIds}
              keyFor={(id) => id}
              renderPill={(id) => (
                <Badge variant="secondary" appearance="light" size="sm">
                  {companyName(companies, id)}
                </Badge>
              )}
            />
          ) : null,
        size: 220,
        enableSorting: false,
      },
      {
        id: 'createdAt',
        accessorFn: (row) => (row.kind === 'key' ? row.createdAt : null),
        meta: { headerTitle: 'Created' },
        header: ({ column }) => <DataGridColumnHeader title="Created" column={column} />,
        cell: ({ row }) =>
          row.original.kind === 'key' ? (
            <span className="text-sm text-muted-foreground">
              {row.original.createdAt ? formatDateTime(row.original.createdAt) : '-'}
            </span>
          ) : null,
        size: 170,
        enableSorting: false,
      },
      {
        id: 'lastUsedAt',
        accessorFn: (row) => (row.kind === 'key' ? row.lastUsedAt : null),
        meta: { headerTitle: 'Last used' },
        header: ({ column }) => <DataGridColumnHeader title="Last used" column={column} />,
        cell: ({ row }) =>
          row.original.kind === 'key' ? (
            <span className="text-sm text-muted-foreground">
              {row.original.lastUsedAt ? formatDateTime(row.original.lastUsedAt) : 'Never'}
            </span>
          ) : null,
        size: 170,
        enableSorting: false,
      },
      {
        id: 'status',
        meta: { headerTitle: 'Status' },
        header: ({ column }) => <DataGridColumnHeader title="Status" column={column} />,
        cell: ({ row }) =>
          row.original.kind === 'key' ? (
            <StatusBadge
              status={row.original.revokedAt ? 'revoked' : 'active'}
              registry={AC_PULL_KEY_STATUS_REGISTRY}
              size="sm"
            />
          ) : null,
        size: 120,
        enableSorting: false,
      },
    ];

    const snapshotColumns: ColumnDef<AutocountPullListRow>[] = [
      {
        id: 'entity',
        accessorFn: (row) => (row.kind === 'snapshot' ? row.entityType : ''),
        meta: { headerTitle: 'Entity', reorderable: false },
        header: ({ column }) => <DataGridColumnHeader title="Entity" column={column} />,
        cell: ({ row }) =>
          row.original.kind === 'snapshot' ? (
            <span className="text-sm font-medium text-foreground">
              {entityLabel(pullEntityFromWire(row.original.entityType))}
            </span>
          ) : null,
        size: 160,
        enableSorting: false,
      },
      {
        id: 'company',
        accessorFn: (row) => (row.kind === 'snapshot' ? row.companyId : ''),
        meta: { headerTitle: 'Company' },
        header: ({ column }) => <DataGridColumnHeader title="Company" column={column} />,
        cell: ({ row }) =>
          row.original.kind === 'snapshot' ? (
            <span className="text-sm text-foreground">{companyName(companies, row.original.companyId)}</span>
          ) : null,
        size: 180,
        enableSorting: false,
      },
      {
        id: 'status',
        accessorFn: (row) => (row.kind === 'snapshot' ? row.status : ''),
        meta: { headerTitle: 'Status' },
        header: ({ column }) => <DataGridColumnHeader title="Status" column={column} />,
        cell: ({ row }) =>
          row.original.kind === 'snapshot' ? (
            <StatusBadge
              status={row.original.status as AutocountPullSnapshotStatus}
              registry={AC_PULL_SNAPSHOT_STATUS_REGISTRY}
              size="sm"
            />
          ) : null,
        size: 130,
        enableSorting: false,
      },
      {
        id: 'records',
        accessorFn: (row) => (row.kind === 'snapshot' ? row.recordCount : 0),
        meta: { headerTitle: 'Records' },
        header: ({ column }) => <DataGridColumnHeader title="Records" column={column} />,
        cell: ({ row }) =>
          row.original.kind === 'snapshot' ? (
            <span className="text-sm text-muted-foreground">
              {row.original.status === 'ready' ? row.original.recordCount.toLocaleString('en-US') : '-'}
            </span>
          ) : null,
        size: 120,
        enableSorting: false,
      },
      {
        id: 'complete',
        accessorFn: (row) => (row.kind === 'snapshot' ? row.complete : false),
        meta: { headerTitle: 'Complete' },
        header: ({ column }) => <DataGridColumnHeader title="Complete" column={column} />,
        cell: ({ row }) =>
          row.original.kind === 'snapshot' && row.original.status === 'ready' ? (
            <Badge variant={row.original.complete ? 'success' : 'warning'} appearance="light" size="sm">
              {row.original.complete ? 'Complete' : 'Partial'}
            </Badge>
          ) : null,
        size: 120,
        enableSorting: false,
      },
      {
        id: 'built',
        accessorFn: (row) => (row.kind === 'snapshot' ? row.extractedAt : null),
        meta: { headerTitle: 'Built' },
        header: ({ column }) => <DataGridColumnHeader title="Built" column={column} />,
        cell: ({ row }) =>
          row.original.kind === 'snapshot' ? (
            <span className="text-sm text-muted-foreground">
              {row.original.extractedAt ? formatDateTime(row.original.extractedAt) : '-'}
            </span>
          ) : null,
        size: 170,
        enableSorting: false,
      },
      {
        id: 'expires',
        accessorFn: (row) => (row.kind === 'snapshot' ? row.expiresAt : null),
        meta: { headerTitle: 'Expires' },
        header: ({ column }) => <DataGridColumnHeader title="Expires" column={column} />,
        cell: ({ row }) =>
          row.original.kind === 'snapshot' ? (
            <span className="text-sm text-muted-foreground">
              {row.original.expiresAt ? formatDateTime(row.original.expiresAt) : '-'}
            </span>
          ) : null,
        size: 170,
        enableSorting: false,
      },
      {
        id: 'requestedVia',
        accessorFn: (row) => (row.kind === 'snapshot' ? row.requestedVia : ''),
        meta: { headerTitle: 'Requested via' },
        header: ({ column }) => <DataGridColumnHeader title="Requested via" column={column} />,
        cell: ({ row }) =>
          row.original.kind === 'snapshot' ? (
            <ClampedText
              text={row.original.requestedVia === 'gateway' ? 'Consumer' : 'Operator'}
              lines={1}
              className="text-sm text-muted-foreground"
            />
          ) : null,
        size: 140,
        enableSorting: false,
      },
    ];

    return {
      viewKey: 'autocount.pull.list',
      columns: activeSegment === 'snapshots' ? snapshotColumns : keyColumns,
      getRowId: pullRowId,
      // The deferred-actions engine parks against the BACKEND row id, never
      // the shell's own prefixed `getRowId` (a union row's discriminant).
      getEntityId: (row) => row.id,
      rowHref: (row) => (row.kind === 'snapshot' ? acPullSnapshotHref(row.id) : '#'),
      fetcher: async (query: ListQuery): Promise<ListResult<AutocountPullListRow>> => {
        const segment = query.segment === 'snapshots' ? 'snapshots' : 'keys';
        setActiveSegment(segment);
        if (segment === 'snapshots') {
          const result = await autocountService.listPullSnapshots({
            page: query.page,
            pageSize: query.pageSize,
          });
          return {
            data: result.data.map((s) => ({ kind: 'snapshot', ...s }) as AutocountPullListRow),
            total: result.total,
            page: result.page,
          };
        }
        const keys = await autocountService.listPullKeys();
        const start = query.page * query.pageSize;
        const data: AutocountPullListRow[] = keys
          .slice(start, start + query.pageSize)
          .map((k) => ({ kind: 'key', ...k }) as AutocountPullListRow);
        return { data, total: keys.length, page: query.page };
      },
      searchPlaceholder: activeSegment === 'snapshots' ? 'Search snapshots' : 'Search keys',
      filterFields: [],
      exportColumns: [],
      actions: [
        {
          id: 'revoke',
          label: 'Revoke',
          tone: 'destructive',
          surfaces: { row: true },
          permission: AC_PULL_MANAGE,
          isVisible: (rows) => rows[0]?.kind === 'key',
          isDisabled: (rows) => rows[0]?.kind === 'key' && Boolean(rows[0].revokedAt),
          // The CORE deferred-action grace window (AC-10-38) - never a
          // hand-rolled confirm dialog. Registered server-side (S3/S4)
          // beside `autocount_etl_task.repush`.
          deferred: { actionKey: 'autocount_pull_api_key.revoke', entityType: 'autocount_pull_api_key' },
        },
      ],
      enableStatusViews: false,
      segments: [
        { id: 'keys', label: 'Keys' },
        { id: 'snapshots', label: 'Snapshots' },
      ],
      defaultSegment: 'keys',
      createLabel: activeSegment === 'snapshots' ? 'Build snapshot' : 'Issue key',
      createPermission: AC_PULL_MANAGE,
      onCreate: activeSegment === 'snapshots' ? onBuildSnapshot : onIssueKey,
    };
  }, [activeSegment, companies, formatDateTime, onBuildSnapshot, onIssueKey]);
}
