'use client';

import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { Badge } from '@/components/ui/badge';
import { ClampedText } from '@/components/platform/clamped-text';
import { StatusBadge } from '@/components/platform/status-badge';
import { embeddedListConfig } from '@/components/platform/resource-list/embedded-list-config';
import type { ResourceListConfig } from '@/components/platform/resource-list';
import { useDatetime } from '@/hooks/use-datetime';
import { autocountService } from '@/services/autocount-service';
import type { AutocountRunOutcome, AutocountSyncRun } from '@/types/autocount';
import type { ListQuery } from '@/types/resource';
import {
  AC_RUN_OUTCOME_REGISTRY,
  acCompanyHref,
  acReviewHref,
  entityLabel,
} from '../../components/autocount-meta';

/**
 * Sync run history embedded on a company's Runs tab. A row opens the batch's
 * review surface - for a decided batch that surface is read-only, which is the
 * honest way to show what was pushed.
 */
export function useAutocountRunsListConfig(
  companyId: string,
): ResourceListConfig<AutocountSyncRun> {
  const { formatDateTime } = useDatetime();

  return useMemo<ResourceListConfig<AutocountSyncRun>>(() => {
    const columns: ColumnDef<AutocountSyncRun>[] = [
      {
        id: 'entityType',
        accessorFn: (row) => row.entityType,
        meta: { headerTitle: 'Entity', reorderable: false },
        header: ({ column }) => <DataGridColumnHeader title="Entity" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm font-medium text-foreground">
            {entityLabel(row.original.entityType)}
          </span>
        ),
        size: 200,
        enableSorting: false,
      },
      {
        id: 'outcome',
        accessorFn: (row) => row.outcome ?? '',
        meta: { headerTitle: 'Outcome' },
        header: ({ column }) => <DataGridColumnHeader title="Outcome" column={column} />,
        cell: ({ row }) => (
          <div className="flex flex-wrap items-start gap-1">
            {row.original.outcome ? (
              <StatusBadge
                status={row.original.outcome as AutocountRunOutcome}
                registry={AC_RUN_OUTCOME_REGISTRY}
                size="sm"
              />
            ) : (
              <Badge variant="info" appearance="light" size="sm">
                Running
              </Badge>
            )}
            {/* A truncated sync must never read as a complete one (AC-13-46). */}
            {row.original.truncated && (
              <Badge variant="warning" appearance="light" size="sm">
                Truncated
              </Badge>
            )}
          </div>
        ),
        size: 170,
        enableSorting: false,
      },
      {
        id: 'counts',
        meta: { headerTitle: 'Records' },
        header: ({ column }) => <DataGridColumnHeader title="Records" column={column} />,
        cell: ({ row }) => {
          const r = row.original;
          return (
            <span className="text-sm text-muted-foreground">
              {r.fetchedCount} fetched · {r.stagedCount} staged
              {r.failedCount > 0 ? ` · ${r.failedCount} failed` : ''}
              {r.pushedCount > 0 ? ` · ${r.pushedCount} pushed` : ''}
            </span>
          );
        },
        size: 280,
        enableSorting: false,
      },
      {
        id: 'finishedAt',
        accessorFn: (row) => row.finishedAt,
        meta: { headerTitle: 'Finished' },
        header: ({ column }) => <DataGridColumnHeader title="Finished" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">
            {row.original.finishedAt ? formatDateTime(row.original.finishedAt) : '-'}
          </span>
        ),
        size: 190,
        enableSorting: false,
      },
      {
        id: 'error',
        accessorFn: (row) => row.error ?? '',
        meta: { headerTitle: 'Error' },
        header: ({ column }) => <DataGridColumnHeader title="Error" column={column} />,
        cell: ({ row }) =>
          row.original.error ? (
            <ClampedText
              text={row.original.error}
              lines={2}
              className="text-sm text-destructive"
            />
          ) : (
            <span className="text-sm text-muted-foreground">-</span>
          ),
        size: 260,
        enableSorting: false,
      },
    ];

    return {
      ...embeddedListConfig<AutocountSyncRun>({
        viewKey: 'autocount.runs.list',
        columns,
        getRowId: (r) => r.id,
        rowHref: (r) => acReviewHref(r.jobId, acCompanyHref(companyId)),
        fetcher: (q: ListQuery) =>
          autocountService.listRuns(companyId, {
            page: q.page,
            pageSize: q.pageSize,
          }),
      }),
      enableStatusViews: false,
    };
  }, [companyId, formatDateTime]);
}
