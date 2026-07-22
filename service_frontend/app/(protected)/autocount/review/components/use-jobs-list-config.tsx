'use client';

import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { ClampedText } from '@/components/platform/clamped-text';
import { StatusBadge } from '@/components/platform/status-badge';
import type { ResourceListConfig } from '@/components/platform/resource-list';
import { useDatetime } from '@/hooks/use-datetime';
import { autocountService } from '@/services/autocount-service';
import type {
  AutocountJobStatus,
  AutocountSyncJobBatch,
} from '@/types/autocount';
import type { ListQuery, ListResult } from '@/types/resource';
import {
  AC_JOB_STATUS_REGISTRY,
  AC_REVIEW_PATH,
  entityLabel,
} from '../../components/autocount-meta';

/**
 * The Review list on the Resource shell (AC-15-02) — one row per sync batch
 * (job), newest first, backed by `GET /autocount/jobs`. Server-paginated and
 * segmented by review state (Needs review | Done | All); a row opens the
 * existing review surface (the form/detail view).
 *
 * There is deliberately no free-text search box wired to the fetcher: the jobs
 * endpoint filters by status/entity, not text, and a box that silently did
 * nothing is a dead control (the same stance the companies list takes). The
 * status segment is the list's real filter.
 */
export function useAutocountJobsListConfig(): ResourceListConfig<AutocountSyncJobBatch> {
  const { formatDateTime } = useDatetime();

  return useMemo<ResourceListConfig<AutocountSyncJobBatch>>(() => {
    const columns: ColumnDef<AutocountSyncJobBatch>[] = [
      {
        id: 'company',
        accessorFn: (row) => row.companyName,
        meta: { headerTitle: 'Company', reorderable: false },
        header: ({ column }) => <DataGridColumnHeader title="Company" column={column} />,
        cell: ({ row }) => (
          <div className="flex min-w-0 flex-col gap-0.5">
            <ClampedText
              text={row.original.companyName || row.original.databaseName}
              lines={1}
              className="text-sm font-medium text-foreground"
            />
            <code className="text-xs text-muted-foreground">
              {row.original.databaseName}
            </code>
          </div>
        ),
        size: 240,
        enableSorting: false,
      },
      {
        id: 'entity',
        accessorFn: (row) => row.entityType,
        meta: { headerTitle: 'Entity' },
        header: ({ column }) => <DataGridColumnHeader title="Entity" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm text-foreground">
            {entityLabel(row.original.entityType)}
          </span>
        ),
        size: 180,
        enableSorting: false,
      },
      {
        id: 'status',
        accessorFn: (row) => row.status,
        meta: { headerTitle: 'Status' },
        header: ({ column }) => <DataGridColumnHeader title="Status" column={column} />,
        cell: ({ row }) => (
          <div className="flex items-start">
            <StatusBadge
              status={row.original.status as AutocountJobStatus}
              registry={AC_JOB_STATUS_REGISTRY}
              size="sm"
            />
          </div>
        ),
        size: 160,
        enableSorting: false,
      },
      {
        id: 'records',
        accessorFn: (row) => row.progressTotal,
        meta: { headerTitle: 'Records' },
        header: ({ column }) => <DataGridColumnHeader title="Records" column={column} />,
        cell: ({ row }) => {
          const { progressTotal, progressFailed } = row.original;
          return (
            <span className="text-sm text-muted-foreground">
              {progressTotal}
              {progressFailed > 0 && (
                <span className="text-destructive"> · {progressFailed} failed</span>
              )}
            </span>
          );
        },
        size: 140,
        enableSorting: false,
      },
      {
        id: 'when',
        accessorFn: (row) => row.updatedAt ?? row.createdAt,
        meta: { headerTitle: 'When' },
        header: ({ column }) => <DataGridColumnHeader title="When" column={column} />,
        cell: ({ row }) => {
          const when = row.original.updatedAt ?? row.original.createdAt;
          return (
            <span className="text-sm text-muted-foreground">
              {when ? formatDateTime(when) : '—'}
            </span>
          );
        },
        size: 180,
        enableSorting: false,
      },
    ];

    return {
      viewKey: 'autocount.jobs.list',
      columns,
      getRowId: (job) => job.jobId,
      rowHref: (job) => `${AC_REVIEW_PATH}/${job.jobId}`,
      fetcher: (q: ListQuery): Promise<ListResult<AutocountSyncJobBatch>> =>
        autocountService.listJobs({
          page: q.page,
          pageSize: q.pageSize,
          status: q.segment ?? 'needs_review',
        }),
      exporter: async () => '',
      filterFields: [],
      exportColumns: [],
      actions: [],
      enableStatusViews: false,
      segments: [
        { id: 'needs_review', label: 'Needs review' },
        { id: 'done', label: 'Done' },
        { id: 'all', label: 'All' },
      ],
      defaultSegment: 'needs_review',
    };
  }, [formatDateTime]);
}
