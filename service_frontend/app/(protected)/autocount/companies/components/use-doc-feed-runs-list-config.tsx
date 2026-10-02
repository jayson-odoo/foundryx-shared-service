'use client';

import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { Badge } from '@/components/ui/badge';
import { ClampedText } from '@/components/platform/clamped-text';
import { embeddedListConfig } from '@/components/platform/resource-list/embedded-list-config';
import type { ResourceListConfig } from '@/components/platform/resource-list';
import { useDatetime } from '@/hooks/use-datetime';
import { formatDurationMs } from '@/lib/autocount-etl';
import { autocountService } from '@/services/autocount-service';
import type { DocFeedKey, DocFeedRun, DocFeedRunOutcome } from '@/types/autocount';
import type { FilterGroup, ListQuery } from '@/types/resource';
import { AC_DOC_FEED_KEYS, AC_DOC_FEED_RUN_OUTCOME_REGISTRY, docFeedLabel, docFeedRunKindLabel } from '../../components/autocount-meta';
import { StatusBadge } from '@/components/platform/status-badge';

/** Read a single equality value out of the (whitelisted) filter for `field` -
 * mirrors `use-staged-list-config.tsx`'s own `readEq`. */
function readEq(filter: FilterGroup | null | undefined, field: string): string | undefined {
  const rule = filter?.rules.find((r) => r.kind === 'condition' && r.field === field);
  return rule && rule.kind === 'condition' && typeof rule.value === 'string' ? rule.value : undefined;
}

/** The window a run covers - a day range for a poll/sweep, nothing for a
 * branch pull (13.9: no per-day windowing there). */
function windowLabel(run: DocFeedRun): string {
  if (!run.dayFrom || !run.dayTo) return '-';
  return run.dayFrom === run.dayTo ? run.dayFrom : `${run.dayFrom} .. ${run.dayTo}`;
}

/** The summary counters that apply to THIS run's kind (plan section 3.1) -
 * absent keys read as 0, never rendered as a false zero for a kind they do
 * not apply to (e.g. `candidates` only means something on a sweep). A null
 * summary (in-flight or legacy failed row) reads '-'; Outcome shows the state. */
function summaryLabel(run: DocFeedRun): string {
  const s = run.summary;
  if (!s) return '-';
  if (run.kind === 'sweep') {
    return `${s.candidates ?? 0} candidate(s), ${s.deactivated ?? 0} deactivated, ${s.notFound ?? 0} not found`;
  }
  const parts = [
    `${s.created ?? 0} created`,
    `${s.updated ?? 0} updated`,
    `${s.unchanged ?? 0} unchanged`,
  ];
  if (s.retryable) parts.push(`${s.retryable} waiting`);
  if (s.failed) parts.push(`${s.failed} failed`);
  if (s.staleIgnored) parts.push(`${s.staleIgnored} stale`);
  return parts.join(', ');
}

/**
 * Document feed run history (AC-14-94, 83) - the tab's second embedded list.
 * A feed filter (`SearchSelect` segment) lets an operator narrow to one of
 * the three feeds; newest first (the fetcher's own default order).
 */
export function useDocFeedRunsListConfig(companyId: string): ResourceListConfig<DocFeedRun> {
  const { formatDateTime } = useDatetime();

  return useMemo<ResourceListConfig<DocFeedRun>>(() => {
    const columns: ColumnDef<DocFeedRun>[] = [
      {
        id: 'feed',
        accessorFn: (row) => row.feed,
        meta: { headerTitle: 'Feed' },
        header: ({ column }) => <DataGridColumnHeader title="Feed" column={column} />,
        cell: ({ row }) => <span className="text-sm font-medium text-foreground">{docFeedLabel(row.original.feed)}</span>,
        size: 160,
        enableSorting: false,
      },
      {
        id: 'kind',
        accessorFn: (row) => row.kind,
        meta: { headerTitle: 'Kind' },
        header: ({ column }) => <DataGridColumnHeader title="Kind" column={column} />,
        cell: ({ row }) => <span className="text-sm text-foreground">{docFeedRunKindLabel(row.original.kind)}</span>,
        size: 100,
        enableSorting: false,
      },
      {
        id: 'dryRun',
        accessorFn: (row) => row.dryRun,
        meta: { headerTitle: 'Dry run' },
        header: ({ column }) => <DataGridColumnHeader title="Dry run" column={column} />,
        cell: ({ row }) =>
          row.original.dryRun ? (
            <Badge variant="info" appearance="light" size="sm">
              Dry run
            </Badge>
          ) : (
            <Badge variant="secondary" appearance="light" size="sm">
              Live
            </Badge>
          ),
        size: 96,
        enableSorting: false,
      },
      {
        id: 'window',
        accessorFn: (row) => windowLabel(row),
        meta: { headerTitle: 'Window' },
        header: ({ column }) => <DataGridColumnHeader title="Window" column={column} />,
        cell: ({ row }) => <span className="text-sm text-muted-foreground">{windowLabel(row.original)}</span>,
        size: 160,
        enableSorting: false,
      },
      {
        id: 'fetchedCount',
        accessorFn: (row) => row.fetchedCount,
        meta: { headerTitle: 'Fetched' },
        header: ({ column }) => <DataGridColumnHeader title="Fetched" column={column} />,
        cell: ({ row }) => <span className="text-sm tabular-nums text-foreground">{row.original.fetchedCount}</span>,
        size: 90,
        enableSorting: false,
      },
      {
        id: 'summary',
        accessorFn: (row) => summaryLabel(row),
        meta: { headerTitle: 'Counters' },
        header: ({ column }) => <DataGridColumnHeader title="Counters" column={column} />,
        cell: ({ row }) => <span className="text-sm text-muted-foreground">{summaryLabel(row.original)}</span>,
        size: 280,
        enableSorting: false,
      },
      {
        id: 'outcome',
        accessorFn: (row) => row.outcome ?? '',
        meta: { headerTitle: 'Outcome' },
        header: ({ column }) => <DataGridColumnHeader title="Outcome" column={column} />,
        cell: ({ row }) => (
          <StatusBadge
            status={(row.original.outcome ?? 'RUNNING') as DocFeedRunOutcome | 'RUNNING'}
            registry={AC_DOC_FEED_RUN_OUTCOME_REGISTRY}
            size="sm"
          />
        ),
        size: 130,
        enableSorting: false,
      },
      {
        id: 'error',
        accessorFn: (row) => row.error ?? '',
        meta: { headerTitle: 'Error' },
        header: ({ column }) => <DataGridColumnHeader title="Error" column={column} />,
        cell: ({ row }) =>
          row.original.error ? (
            <ClampedText text={row.original.error} lines={2} className="text-sm text-destructive" />
          ) : (
            <span className="text-sm text-muted-foreground">-</span>
          ),
        size: 220,
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
        size: 170,
        enableSorting: false,
      },
      {
        id: 'durationMs',
        accessorFn: (row) => row.durationMs ?? 0,
        meta: { headerTitle: 'Duration' },
        header: ({ column }) => <DataGridColumnHeader title="Duration" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm tabular-nums text-muted-foreground">
            {row.original.durationMs !== null ? formatDurationMs(row.original.durationMs) : '-'}
          </span>
        ),
        size: 90,
        enableSorting: false,
      },
    ];

    return {
      ...embeddedListConfig<DocFeedRun>({
        viewKey: 'autocount.doc-feed-runs.list',
        columns,
        getRowId: (r) => r.id,
        rowHref: () => '#',
        fetcher: (query: ListQuery) =>
          autocountService.listDocFeedRuns(companyId, {
            page: query.page,
            pageSize: query.pageSize,
            feed: readEq(query.filter, 'feed') as DocFeedKey | undefined,
          }),
      }),
      filterFields: [
        {
          field: 'feed',
          label: 'Feed',
          type: 'enum',
          options: AC_DOC_FEED_KEYS.map((feed) => ({ label: docFeedLabel(feed), value: feed })),
        },
      ],
      enableStatusViews: false,
    };
  }, [companyId, formatDateTime]);
}
