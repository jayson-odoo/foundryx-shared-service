'use client';

import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import {
  JOB_STATUS_LABEL,
  JOB_STATUS_TONE,
  jobProgressPct,
  jobTypeLabel,
} from '@/components/platform/jobs-drawer';
import type { ResourceListConfig } from '@/components/platform/resource-list';
import { jobsService } from '@/services/jobs-service';
import { useDatetime } from '@/hooks/use-datetime';
import type { ListQuery, ListResult } from '@/types/resource';
import type { Job, JobStatus } from '@/types/jobs';
import { useJobActions } from './use-job-actions';
import { CheckCheck } from 'lucide-react';
import { useFx } from '@/hooks/use-fx';
import { FxJobBar, FxJobChip } from '@/components/platform/jobs-drawer/fx-job-chip';
import { fmtCount, jobItem } from '@/components/platform/jobs-drawer/fx-job-items';

const stop = (e: React.MouseEvent) => e.stopPropagation();

/** Segment id → server status filter (All = no filter). */
const SEGMENT_STATUS: Record<string, JobStatus | undefined> = {
  all: undefined,
  running: 'running',
  needs_review: 'needs_review',
  done: 'done',
  failed: 'failed',
};

const SEGMENTS = [
  { id: 'all', label: 'All' },
  { id: 'running', label: 'Running' },
  { id: 'needs_review', label: 'Needs review' },
  { id: 'done', label: 'Done' },
  { id: 'failed', label: 'Failed' },
];

/**
 * `/jobs` list config (sprint-4/10 AC-10-19) - the generic background-jobs
 * history on the Resource shell. Type + Status + progress columns; N-way status
 * segments. The backend list is page-based only, so search/sort/filter are not
 * wired server-side (the fetcher passes page/pageSize + the segment's status).
 */
export function useJobsListConfig(): ResourceListConfig<Job> {
  const { formatDateTime } = useDatetime();
  const actions = useJobActions();
  // Foundryx UIUX: only the status and progress cells read differently.
  const fx = useFx();

  return useMemo<ResourceListConfig<Job>>(() => {
    const columns: ColumnDef<Job>[] = [
      {
        id: 'type',
        accessorFn: (row) => row.type,
        meta: { headerTitle: 'Type', reorderable: false },
        header: ({ column }) => <DataGridColumnHeader title="Type" column={column} />,
        cell: ({ row }) => (
          <span className="text-foreground text-sm font-medium">
            {jobTypeLabel(row.original.type)}
          </span>
        ),
        size: 200,
        enableSorting: false,
      },
      {
        id: 'status',
        accessorFn: (row) => row.status,
        meta: { headerTitle: 'Status' },
        header: ({ column }) => <DataGridColumnHeader title="Status" column={column} />,
        cell: ({ row }) => {
          if (fx) {
            const item = jobItem(row.original);
            return <FxJobChip label={item.status} tone={item.tone} />;
          }
          return (
            <Badge variant={JOB_STATUS_TONE[row.original.status]} appearance="light">
              {JOB_STATUS_LABEL[row.original.status]}
            </Badge>
          );
        },
        size: 140,
        enableSorting: false,
      },
      {
        id: 'progress',
        meta: { headerTitle: 'Progress' },
        header: ({ column }) => <DataGridColumnHeader title="Progress" column={column} />,
        cell: ({ row }) => {
          const j = row.original;
          if (j.progressTotal <= 0) {
            return <span className="text-muted-foreground text-sm">-</span>;
          }
          if (fx) {
            const text = `${fmtCount(j.progressDone)} of ${fmtCount(j.progressTotal)}${
              j.progressFailed ? ` · ${fmtCount(j.progressFailed)} failed` : ''
            }`;
            return (
              <div className="flex min-w-32 flex-col gap-1">
                <FxJobBar pct={jobProgressPct(j.progressDone, j.progressTotal)} label={text} />
                <span className="text-xs text-(--fx-ink-2) tabular-nums">{text}</span>
              </div>
            );
          }
          return (
            <div className="flex min-w-32 flex-col gap-1">
              <Progress value={jobProgressPct(j.progressDone, j.progressTotal)} className="h-1.5" />
              <span className="text-muted-foreground text-xs">
                {j.progressDone}/{j.progressTotal}
                {j.progressFailed ? ` · ${j.progressFailed} failed` : ''}
              </span>
            </div>
          );
        },
        size: 180,
        enableSorting: false,
      },
      {
        id: 'created',
        accessorFn: (row) => row.createdAt,
        meta: { headerTitle: 'Started' },
        header: ({ column }) => <DataGridColumnHeader title="Started" column={column} />,
        cell: ({ row }) => (
          <span className="text-muted-foreground text-sm">
            {formatDateTime(row.original.createdAt)}
          </span>
        ),
        size: 190,
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
                runtime={{ reload: meta?.reload ?? (() => {}) }}
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

    return {
      viewKey: 'jobs.list',
      columns,
      getRowId: (j) => j.id,
      rowHref: (j) => `/jobs/${j.id}`,
      fetcher: (q: ListQuery): Promise<ListResult<Job>> =>
        jobsService
          .listJobs({
            page: q.page,
            pageSize: q.pageSize,
            status: q.segment ? SEGMENT_STATUS[q.segment] : undefined,
          })
          .then((r) => ({ data: r.items, total: r.total, page: q.page })),
      filterFields: [],
      exportColumns: [],
      actions,
      segments: SEGMENTS,
      defaultSegment: 'all',
      enableStatusViews: false,
      fx: {
        noun: 'jobs',
        columnKind: { status: 'status' },
        iconFor: { abort: 'close', retry: 'refresh', complete: <CheckCheck /> },
        cardLines: [['type', 'status'], ['progress'], ['created']],
      },
    };
  }, [actions, formatDateTime, fx]);
}
