'use client';

import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { Badge } from '@/components/ui/badge';
import { ClampedText } from '@/components/platform/clamped-text';
import { StatusBadge } from '@/components/platform/status-badge';
import { embeddedListConfig } from '@/components/platform/resource-list/embedded-list-config';
import type { ResourceListConfig } from '@/components/platform/resource-list';
import { autocountService } from '@/services/autocount-service';
import type {
  AutocountStagedRecord,
  AutocountStagedStatus,
} from '@/types/autocount';
import type { FilterGroup, ListQuery, ListResult } from '@/types/resource';
import { AC_STAGED_STATUS_REGISTRY, entityLabel } from '../../../components/autocount-meta';

/** A click on the row body opens the diff; nothing else steals the click. */
function recordName(record: AutocountStagedRecord): string {
  const name = record.canonical?.name;
  return typeof name === 'string' ? name : '';
}

/** Read a single equality value out of the (whitelisted) filter for `field`. */
function readEq(filter: FilterGroup | null | undefined, field: string): string | undefined {
  const rule = filter?.rules.find(
    (r) => r.kind === 'condition' && r.field === field,
  );
  return rule && rule.kind === 'condition' && typeof rule.value === 'string'
    ? rule.value
    : undefined;
}

export interface StagedListConfigOptions {
  jobId: string;
  /**
   * Which partition this list serves: `true` = records the operator must act on
   * (changed / failed); `false` = the collapsed no-change set. Fixed per list
   * instance - the no-change collapse mounts a second list with `false`.
   */
  changed: boolean;
  /** Open a record's full diff (detail drawer) - the diff is not forced inline. */
  onOpenRecord: (record: AutocountStagedRecord) => void;
}

/**
 * The staged-record list on the Resource shell (AC-15-10) - server-paginated,
 * searchable (source ref / doc no / name) and status-filterable, replacing the
 * tall full-card-per-record stack. Each row is a scannable line; the full
 * before → after diff is reached by opening the row (`onOpenRecord`), never
 * rendered inline for every record.
 */
export function useStagedListConfig({
  jobId,
  changed,
  onOpenRecord,
}: StagedListConfigOptions): ResourceListConfig<AutocountStagedRecord> {
  return useMemo<ResourceListConfig<AutocountStagedRecord>>(() => {
    const columns: ColumnDef<AutocountStagedRecord>[] = [
      {
        id: 'sourceRef',
        accessorFn: (row) => row.sourceRef,
        meta: { headerTitle: 'Reference', reorderable: false },
        header: ({ column }) => <DataGridColumnHeader title="Reference" column={column} />,
        cell: ({ row }) => (
          <div className="flex min-w-0 flex-col gap-0.5">
            <ClampedText
              text={row.original.docNo || row.original.sourceRef}
              lines={1}
              className="text-sm font-medium text-foreground"
            />
            {row.original.docNo && (
              <span className="text-xs text-muted-foreground">{row.original.sourceRef}</span>
            )}
          </div>
        ),
        size: 200,
        enableSorting: false,
      },
      {
        id: 'name',
        accessorFn: (row) => recordName(row),
        meta: { headerTitle: 'Name' },
        header: ({ column }) => <DataGridColumnHeader title="Name" column={column} />,
        cell: ({ row }) => (
          <div className="flex min-w-0 flex-col gap-0.5">
            <ClampedText
              text={recordName(row.original) || '-'}
              lines={1}
              className="text-sm text-foreground"
            />
            <span className="text-xs text-muted-foreground">
              {entityLabel(row.original.entityType)}
            </span>
          </div>
        ),
        size: 220,
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
              status={row.original.status as AutocountStagedStatus}
              registry={AC_STAGED_STATUS_REGISTRY}
              size="sm"
            />
          </div>
        ),
        size: 150,
        enableSorting: false,
      },
      {
        id: 'change',
        accessorFn: (row) => row.hasChanges,
        meta: { headerTitle: 'Change' },
        header: ({ column }) => <DataGridColumnHeader title="Change" column={column} />,
        cell: ({ row }) => (
          <div className="flex items-start">
            <Badge
              variant={row.original.hasChanges ? 'info' : 'secondary'}
              appearance="light"
              size="sm"
            >
              {row.original.hasChanges ? 'Changed' : 'No change'}
            </Badge>
          </div>
        ),
        size: 120,
        enableSorting: false,
      },
    ];

    return {
      ...embeddedListConfig<AutocountStagedRecord>({
        viewKey: 'autocount.staged.list',
        columns,
        getRowId: (row) => row.id,
        rowHref: () => '#',
        searchPlaceholder: 'Search by reference or name',
        fetcher: async (query: ListQuery): Promise<ListResult<AutocountStagedRecord>> => {
          const res = await autocountService.listStaged(jobId, {
            page: query.page,
            pageSize: query.pageSize,
            search: query.search,
            changed,
            status: readEq(query.filter, 'status'),
          });
          return { data: res.data, total: res.total, page: query.page };
        },
      }),
      searchHints: ['Reference', 'Name'],
      filterFields: [
        {
          field: 'status',
          label: 'Status',
          type: 'enum',
          options: [
            { label: 'Awaiting approval', value: 'STAGED' },
            { label: 'Failed', value: 'FAILED' },
            { label: 'Pushed', value: 'PUSHED' },
            { label: 'Discarded', value: 'DISCARDED' },
          ],
        },
      ],
      onRowSelect: (row) => onOpenRecord(row),
      enableStatusViews: false,
    };
  }, [jobId, changed, onOpenRecord]);
}
