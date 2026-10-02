'use client';

import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import { embeddedListConfig } from '@/components/platform/resource-list/embedded-list-config';
import type { ResourceAction, ResourceListConfig } from '@/components/platform/resource-list';
import { StatusBadge } from '@/components/platform/status-badge';
import { JobProgress } from '@/components/platform/autocount/job-progress';
import { useDatetime } from '@/hooks/use-datetime';
import type { DocFeedItem, DocFeedKey, DocFeedMode, DocFeedRunOutcome } from '@/types/autocount';
import {
  AC_COMPANIES_MANAGE,
  AC_DOC_FEED_BACKFILL_STATUS_REGISTRY,
  AC_DOC_FEED_MODE_REGISTRY,
  AC_DOC_FEED_RUN_OUTCOME_REGISTRY,
  AC_SYNC_RUN,
  docFeedLabel,
} from '../../components/autocount-meta';

function stopRowClick(e: React.MouseEvent) {
  e.stopPropagation();
}

export interface DocFeedsListOptions {
  feeds: DocFeedItem[];
  onConfigure: (feed: DocFeedKey) => void;
  onRunNow: (feed: DocFeedKey) => void;
  onRunSweepNow: (feed: DocFeedKey) => void;
  onBackfill: (feed: DocFeedKey) => void;
  onStopBackfill: (feed: DocFeedKey) => void;
  onResumeBackfill: (feed: DocFeedKey) => void;
  onDiscardBackfill: (feed: DocFeedKey) => void;
}

function hasOpenBackfill(item: DocFeedItem): boolean {
  // S6 (review round 1) - the backend's own open statuses (`running`,
  // `stopping`, `stopped`) all mean "there is a backfill to finish or
  // discard first" (`DOC_FEED_BACKFILL_OPEN_STATUSES`); only `done` frees
  // up a fresh Backfill. A `stopped` backfill previously still offered
  // "Backfill...", which always 409d (foolproof-UI: no invalid options).
  return Boolean(item.backfill && item.backfill.status !== 'done');
}

/**
 * The "Document feeds" tab's own list - fixed rows, one per feed (D2: a
 * never-configured feed still renders `off`, never a blank/missing row).
 * Row actions come from `ActionMenu` gated by `useCan` (AC-14-92): only the
 * actions valid for the row's OWN state are ever listed, never shown-but-
 * disabled (foolproof-UI).
 */
export function useDocFeedsListConfig(options: DocFeedsListOptions): ResourceListConfig<DocFeedItem> {
  const { formatDateTime } = useDatetime();
  const {
    feeds,
    onConfigure,
    onRunNow,
    onRunSweepNow,
    onBackfill,
    onStopBackfill,
    onResumeBackfill,
    onDiscardBackfill,
  } = options;

  return useMemo<ResourceListConfig<DocFeedItem>>(() => {
    const actions: ResourceAction<DocFeedItem>[] = [
      {
        id: 'configure',
        label: 'Configure',
        surfaces: { row: true },
        permission: AC_COMPANIES_MANAGE,
        run: (rows) => onConfigure(rows[0].feed),
      },
      {
        id: 'run-now',
        label: 'Run now',
        surfaces: { row: true },
        permission: AC_SYNC_RUN,
        isVisible: (rows) => rows[0].mode !== 'off',
        run: (rows) => onRunNow(rows[0].feed),
      },
      {
        id: 'run-sweep-now',
        label: 'Run sweep now',
        surfaces: { row: true },
        permission: AC_SYNC_RUN,
        isVisible: (rows) => rows[0].mode !== 'off',
        run: (rows) => onRunSweepNow(rows[0].feed),
      },
      {
        id: 'backfill',
        // Only ever visible when there is no backfill yet or the last one
        // is `done` (S6) - never a reason to show the ellipsis variant.
        label: 'Backfill',
        surfaces: { row: true },
        permission: AC_SYNC_RUN,
        isVisible: (rows) => rows[0].mode !== 'off' && !hasOpenBackfill(rows[0]),
        run: (rows) => onBackfill(rows[0].feed),
      },
      {
        id: 'stop-backfill',
        label: 'Stop backfill',
        surfaces: { row: true },
        permission: AC_SYNC_RUN,
        // A stopped backfill is already stopped - Stop would be a no-op.
        isVisible: (rows) => rows[0].backfill?.status === 'running',
        run: (rows) => onStopBackfill(rows[0].feed),
      },
      {
        id: 'resume-backfill',
        label: 'Resume backfill',
        surfaces: { row: true },
        permission: AC_SYNC_RUN,
        // The backend refuses Resume on an Off feed (422 mode).
        isVisible: (rows) => rows[0].backfill?.status === 'stopped' && rows[0].mode !== 'off',
        run: (rows) => onResumeBackfill(rows[0].feed),
      },
      {
        id: 'discard-backfill',
        label: 'Discard backfill',
        tone: 'destructive',
        surfaces: { row: true },
        permission: AC_SYNC_RUN,
        isVisible: (rows) => rows[0].backfill?.status === 'stopped',
        run: (rows) => onDiscardBackfill(rows[0].feed),
      },
    ];

    const columns: ColumnDef<DocFeedItem>[] = [
      {
        id: 'feed',
        accessorFn: (row) => row.feed,
        meta: { headerTitle: 'Feed', reorderable: false },
        header: ({ column }) => <DataGridColumnHeader title="Feed" column={column} />,
        cell: ({ row }) => <span className="text-sm font-medium text-foreground">{docFeedLabel(row.original.feed)}</span>,
        size: 180,
        enableSorting: false,
      },
      {
        id: 'book',
        accessorFn: (row) => row.book ?? '',
        meta: { headerTitle: 'Book' },
        header: ({ column }) => <DataGridColumnHeader title="Book" column={column} />,
        cell: ({ row }) => <span className="text-sm text-muted-foreground">{row.original.book ?? '-'}</span>,
        size: 90,
        enableSorting: false,
      },
      {
        id: 'mode',
        accessorFn: (row) => row.mode,
        meta: { headerTitle: 'Mode' },
        header: ({ column }) => <DataGridColumnHeader title="Mode" column={column} />,
        cell: ({ row }) => (
          <StatusBadge status={row.original.mode as DocFeedMode} registry={AC_DOC_FEED_MODE_REGISTRY} size="sm" />
        ),
        size: 100,
        enableSorting: false,
      },
      {
        id: 'cursorDay',
        accessorFn: (row) => row.cursorDay ?? '',
        meta: { headerTitle: 'Covered through' },
        header: ({ column }) => <DataGridColumnHeader title="Covered through" column={column} />,
        cell: ({ row }) => <span className="text-sm text-muted-foreground">{row.original.cursorDay ?? '-'}</span>,
        size: 140,
        enableSorting: false,
      },
      {
        id: 'lastRun',
        accessorFn: (row) => row.lastRun?.finishedAt ?? '',
        meta: { headerTitle: 'Last run' },
        header: ({ column }) => <DataGridColumnHeader title="Last run" column={column} />,
        cell: ({ row }) => {
          const lastRun = row.original.lastRun;
          if (!lastRun) return <span className="text-sm text-muted-foreground">Never run</span>;
          return (
            <div className="flex flex-col gap-1">
              <span className="text-sm text-foreground">
                {lastRun.finishedAt ? formatDateTime(lastRun.finishedAt) : 'Running…'}
              </span>
              {lastRun.outcome && (
                <StatusBadge
                  status={lastRun.outcome as DocFeedRunOutcome}
                  registry={AC_DOC_FEED_RUN_OUTCOME_REGISTRY}
                  size="sm"
                />
              )}
            </div>
          );
        },
        size: 190,
        enableSorting: false,
      },
      {
        id: 'retryableCount',
        accessorFn: (row) => row.retryableCount,
        meta: { headerTitle: 'Waiting' },
        header: ({ column }) => <DataGridColumnHeader title="Waiting" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm tabular-nums text-foreground">{row.original.retryableCount}</span>
        ),
        size: 90,
        enableSorting: false,
      },
      {
        id: 'failedCount',
        accessorFn: (row) => row.failedCount,
        meta: { headerTitle: 'Failed' },
        header: ({ column }) => <DataGridColumnHeader title="Failed" column={column} />,
        cell: ({ row }) => (
          <span className={row.original.failedCount > 0 ? 'text-sm tabular-nums text-destructive' : 'text-sm tabular-nums text-muted-foreground'}>
            {row.original.failedCount}
          </span>
        ),
        size: 90,
        enableSorting: false,
      },
      {
        id: 'backfill',
        accessorFn: (row) => row.backfill?.status ?? '',
        meta: { headerTitle: 'Backfill' },
        header: ({ column }) => <DataGridColumnHeader title="Backfill" column={column} />,
        cell: ({ row }) => {
          const backfill = row.original.backfill;
          if (!backfill) return <span className="text-sm text-muted-foreground">-</span>;
          if (backfill.status === 'running' || backfill.status === 'stopping') {
            return (
              <JobProgress
                status={backfill.status === 'stopping' ? 'cancelling' : 'running'}
                stage={null}
                pagesDone={backfill.daysDone}
                pagesTotal={backfill.daysTotal}
                unit="days"
              />
            );
          }
          return (
            <StatusBadge status={backfill.status} registry={AC_DOC_FEED_BACKFILL_STATUS_REGISTRY} size="sm" />
          );
        },
        size: 220,
        enableSorting: false,
      },
      {
        id: 'actions',
        meta: { reorderable: false },
        header: () => null,
        cell: ({ row, table }) => (
          <div onClick={stopRowClick} className="flex justify-end">
            <ActionMenu
              actions={actions}
              rows={[row.original]}
              runtime={{ reload: table.options.meta?.reload ?? (() => {}) }}
              surface="row"
            />
          </div>
        ),
        size: 60,
        enableSorting: false,
        enableHiding: false,
      },
    ];

    return {
      ...embeddedListConfig<DocFeedItem>({
        viewKey: 'autocount.doc-feeds.list',
        columns,
        getRowId: (r) => r.feed,
        rowHref: () => '#',
        fetcher: async () => ({ data: feeds, total: feeds.length, page: 0 }),
        actions,
      }),
      enableStatusViews: false,
    };
  }, [
    feeds,
    formatDateTime,
    onBackfill,
    onConfigure,
    onDiscardBackfill,
    onResumeBackfill,
    onRunNow,
    onRunSweepNow,
    onStopBackfill,
  ]);
}
