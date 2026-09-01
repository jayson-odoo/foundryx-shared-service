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
import { formatDurationMs } from '@/lib/autocount-etl';
import { autocountService } from '@/services/autocount-service';
import type {
  AutocountRunMode,
  AutocountRunOutcome,
  AutocountSyncRun,
} from '@/types/autocount';
import type { ListQuery } from '@/types/resource';
import {
  AC_RUN_MODE_REGISTRY,
  AC_RUN_OUTCOME_REGISTRY,
  acCompanyHref,
  acReviewHref,
  acTaskHref,
  entityLabel,
} from '../../components/autocount-meta';

export interface RunsListOptions {
  /**
   * `company` (default) = every entity's runs on the company's Runs tab.
   * `task` (plan 22 S2, AC-22-17) = ONE entity's history on its task editor:
   * the cost columns (mode, rows scanned, added/updated/deleted/failed,
   * duration) so volume × frequency is judgeable per run; a skipped tick
   * renders its reason, a failed run its error. Requires `entityType`.
   */
  variant?: 'company' | 'task';
  entityType?: string;
}

/** A count cell; `-` where the number does not apply (e.g. deletes on an
 * incremental run, anything on a skipped tick). */
function Count({ value, muted = false }: { value: number; muted?: boolean }) {
  return (
    <span
      className={
        value > 0 && !muted ? 'text-sm tabular-nums text-foreground' : 'text-sm tabular-nums text-muted-foreground'
      }
    >
      {muted ? '-' : value}
    </span>
  );
}

/**
 * Sync run history embedded on a company's Runs tab (and, in `task` mode, on
 * the DB task editor's Runs tab). A row opens the batch's review surface - the
 * per-record verdicts live there - for a decided batch that surface is
 * read-only, which is the honest way to show what was pushed.
 */
export function useAutocountRunsListConfig(
  companyId: string,
  options: RunsListOptions = {},
): ResourceListConfig<AutocountSyncRun> {
  const { formatDateTime } = useDatetime();
  const variant = options.variant ?? 'company';
  const entityType = options.entityType;

  return useMemo<ResourceListConfig<AutocountSyncRun>>(() => {
    const outcomeCell = (r: AutocountSyncRun) => (
      <div className="flex min-w-0 flex-col items-start gap-1">
        <div className="flex flex-wrap items-start gap-1">
          {r.outcome ? (
            <StatusBadge
              status={r.outcome as AutocountRunOutcome}
              registry={AC_RUN_OUTCOME_REGISTRY}
              size="sm"
            />
          ) : (
            <Badge variant="info" appearance="light" size="sm">
              Running
            </Badge>
          )}
          {/* A truncated sync must never read as a complete one (AC-13-46). */}
          {r.truncated && (
            <Badge variant="warning" appearance="light" size="sm">
              Truncated
            </Badge>
          )}
          {variant === 'task' &&
            r.outcome === 'SUCCESS' &&
            r.addedCount + r.updatedCount + r.deletedCount + r.failedCount === 0 && (
              <Badge variant="secondary" appearance="light" size="sm">
                No changes
              </Badge>
            )}
        </div>
        {/* Why a tick was skipped / why a run failed - stated on the row, never
            buried in a detail page (AC-22-14/19). */}
        {r.skipReason && (
          <ClampedText text={r.skipReason} lines={2} className="text-xs text-muted-foreground" />
        )}
        {r.error && <ClampedText text={r.error} lines={2} className="text-xs text-destructive" />}
      </div>
    );

    const companyColumns: ColumnDef<AutocountSyncRun>[] = [
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
        cell: ({ row }) => outcomeCell(row.original),
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

    const countColumn = (
      id: 'rowsScanned' | 'addedCount' | 'updatedCount' | 'deletedCount' | 'failedCount',
      title: string,
      appliesTo: (r: AutocountSyncRun) => boolean,
    ): ColumnDef<AutocountSyncRun> => ({
      id,
      accessorFn: (row) => row[id],
      meta: { headerTitle: title },
      header: ({ column }) => <DataGridColumnHeader title={title} column={column} />,
      cell: ({ row }) => <Count value={row.original[id]} muted={!appliesTo(row.original)} />,
      size: 76,
      enableSorting: false,
    });
    const ran = (r: AutocountSyncRun) => r.mode !== 'skipped';

    const taskColumns: ColumnDef<AutocountSyncRun>[] = [
      {
        id: 'startedAt',
        accessorFn: (row) => row.startedAt,
        meta: { headerTitle: 'Started', reorderable: false },
        header: ({ column }) => <DataGridColumnHeader title="Started" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm text-foreground">
            {row.original.startedAt ? formatDateTime(row.original.startedAt) : '-'}
          </span>
        ),
        size: 160,
        enableSorting: false,
      },
      {
        id: 'mode',
        accessorFn: (row) => row.mode,
        meta: { headerTitle: 'Mode' },
        header: ({ column }) => <DataGridColumnHeader title="Mode" column={column} />,
        cell: ({ row }) => (
          <div className="flex items-start">
            <StatusBadge
              status={row.original.mode as AutocountRunMode}
              registry={AC_RUN_MODE_REGISTRY}
              size="sm"
            />
          </div>
        ),
        size: 116,
        enableSorting: false,
      },
      countColumn('rowsScanned', 'Scanned', ran),
      countColumn('addedCount', 'Added', ran),
      countColumn('updatedCount', 'Updated', ran),
      countColumn('deletedCount', 'Deleted', (r) => r.mode === 'reconcile'),
      countColumn('failedCount', 'Failed', ran),
      {
        id: 'durationMs',
        accessorFn: (row) => row.durationMs ?? 0,
        meta: { headerTitle: 'Duration' },
        header: ({ column }) => <DataGridColumnHeader title="Duration" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm tabular-nums text-muted-foreground">
            {formatDurationMs(row.original.durationMs)}
          </span>
        ),
        size: 90,
        enableSorting: false,
      },
      {
        id: 'outcome',
        accessorFn: (row) => row.outcome ?? '',
        meta: { headerTitle: 'Outcome' },
        header: ({ column }) => <DataGridColumnHeader title="Outcome" column={column} />,
        cell: ({ row }) => outcomeCell(row.original),
        size: 220,
        enableSorting: false,
      },
    ];

    const backHref =
      variant === 'task' && entityType
        ? acTaskHref(companyId, entityType, 'runs')
        : acCompanyHref(companyId);

    return {
      ...embeddedListConfig<AutocountSyncRun>({
        viewKey: variant === 'task' ? 'autocount.task-runs.list' : 'autocount.runs.list',
        columns: variant === 'task' ? taskColumns : companyColumns,
        getRowId: (r) => r.id,
        // A skipped tick enqueued nothing - there is no batch to open ('#' =
        // the shell's no-navigation contract).
        rowHref: (r) => (r.jobId ? acReviewHref(r.jobId, backHref) : '#'),
        fetcher: (q: ListQuery) =>
          variant === 'task' && entityType
            ? autocountService.listEtlRuns(companyId, entityType, {
                page: q.page,
                pageSize: q.pageSize,
              })
            : autocountService.listRuns(companyId, {
                page: q.page,
                pageSize: q.pageSize,
              }),
      }),
      enableStatusViews: false,
    };
  }, [companyId, entityType, formatDateTime, variant]);
}
