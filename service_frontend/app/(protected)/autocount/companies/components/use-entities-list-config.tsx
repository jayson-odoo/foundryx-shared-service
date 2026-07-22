'use client';

import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { CalendarRange, RefreshCw } from 'lucide-react';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { Badge } from '@/components/ui/badge';
import { ClampedText } from '@/components/platform/clamped-text';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import { embeddedListConfig } from '@/components/platform/resource-list/embedded-list-config';
import type { ResourceAction, ResourceListConfig } from '@/components/platform/resource-list';
import { useDatetime } from '@/hooks/use-datetime';
import type { AutocountEntityConfig } from '@/types/autocount';
import type { ListQuery, ListResult } from '@/types/resource';
import {
  AC_COMPANIES_MANAGE,
  AC_SYNC_RUN,
  entityLabel,
  syncModeLabel,
} from '../../components/autocount-meta';

/**
 * The Entities tab's list.
 *
 * On the Resource shell rather than the hand-rolled rows it replaces: the
 * catalogue is heading for nine-plus entities (Stock, Product, Supplier,
 * Debtor, Warehouse, Tax, Terms, DO, GRN), each with its own sync mode,
 * schedule, record cap and watermark, and a stacked list of bespoke rows does
 * not survive that.
 *
 * The columns are chosen to make a ZERO-RECORD SYNC SELF-EXPLANATORY, which is
 * the whole reason this tab exists: "Synced up to" is the delta position, so a
 * run finding nothing is visibly "nothing changed since then" rather than
 * silence; "First-run window" exposes the 30-day default that otherwise hides a
 * customer's entire back-catalogue on a newly connected company; and the health
 * column finally renders `consecutiveFailures`/`lastError`, which every run has
 * been recording and nothing displayed.
 */

/** A click inside the row's action cell must not also open the row. */
const stopRowClick = (event: React.MouseEvent) => event.stopPropagation();

/** Sortable/searchable in memory: the rows arrive whole on the company detail,
 * so there is no server-paginated endpoint to defer to (the same adapter the
 * Terminology settings list uses). */
function paginate(
  rows: AutocountEntityConfig[],
  query: ListQuery,
): ListResult<AutocountEntityConfig> {
  const term = (query.search ?? '').trim().toLowerCase();
  const matched = term
    ? rows.filter(
        (row) =>
          entityLabel(row.entityType).toLowerCase().includes(term) ||
          syncModeLabel(row.syncMode).toLowerCase().includes(term),
      )
    : rows;
  const start = query.page * query.pageSize;
  return {
    data: matched.slice(start, start + query.pageSize),
    total: matched.length,
    page: query.page,
  };
}

export interface EntitiesListConfigOptions {
  entities: AutocountEntityConfig[];
  /** False when the company is inactive — a sync could not succeed. */
  companyActive: boolean;
  onSync: (entityType: string) => void | Promise<void>;
  onEditLookback: (entity: AutocountEntityConfig) => void;
}

export function useAutocountEntitiesListConfig({
  entities,
  companyActive,
  onSync,
  onEditLookback,
}: EntitiesListConfigOptions): ResourceListConfig<AutocountEntityConfig> {
  const { formatDateTime } = useDatetime();

  return useMemo<ResourceListConfig<AutocountEntityConfig>>(() => {
    const actions: ResourceAction<AutocountEntityConfig>[] = [
      {
        id: 'sync-now',
        label: 'Sync now',
        icon: RefreshCw,
        surfaces: { row: true },
        permission: AC_SYNC_RUN,
        // Foolproof-UI: offered only where it can succeed, never offered and
        // then failed.
        isDisabled: (rows) => !companyActive || rows.some((row) => !row.enabled),
        run: (rows) => {
          const row = rows[0];
          if (row) return onSync(row.entityType);
        },
      },
      {
        id: 'edit-lookback',
        label: 'Edit first-run window',
        icon: CalendarRange,
        surfaces: { row: true },
        permission: AC_COMPANIES_MANAGE,
        run: (rows) => {
          const row = rows[0];
          if (row) onEditLookback(row);
        },
      },
    ];

    const columns: ColumnDef<AutocountEntityConfig>[] = [
      {
        id: 'entityType',
        accessorFn: (row) => row.entityType,
        meta: { headerTitle: 'Entity', reorderable: false },
        header: ({ column }) => <DataGridColumnHeader title="Entity" column={column} />,
        cell: ({ row }) => (
          <div className="flex min-w-0 flex-col gap-0.5">
            <span className="text-sm font-medium text-foreground">
              {entityLabel(row.original.entityType)}
            </span>
            {!row.original.enabled && (
              <span className="text-xs text-muted-foreground">Not enabled for sync</span>
            )}
          </div>
        ),
        size: 180,
        enableSorting: false,
      },
      {
        id: 'syncMode',
        accessorFn: (row) => row.syncMode,
        meta: { headerTitle: 'Sync mode' },
        header: ({ column }) => (
          <DataGridColumnHeader title="Sync mode" column={column} />
        ),
        cell: ({ row }) => (
          <div className="flex min-w-0 flex-col gap-0.5">
            <span className="text-sm text-foreground">
              {syncModeLabel(row.original.syncMode)}
            </span>
            <span className="text-xs text-muted-foreground">
              up to {row.original.recordCap} records per run
            </span>
          </div>
        ),
        size: 170,
        enableSorting: false,
      },
      {
        id: 'lastSuccessAt',
        accessorFn: (row) => row.lastSuccessAt,
        meta: { headerTitle: 'Last synced' },
        header: ({ column }) => (
          <DataGridColumnHeader title="Last synced" column={column} />
        ),
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">
            {row.original.lastSuccessAt
              ? formatDateTime(row.original.lastSuccessAt)
              : 'Never'}
          </span>
        ),
        size: 170,
        enableSorting: false,
      },
      {
        id: 'watermarkAt',
        // The delta position. This is the column that makes "0 records" read as
        // "nothing has changed since then" instead of as a silent failure.
        accessorFn: (row) => row.watermarkAt,
        meta: { headerTitle: 'Synced up to' },
        header: ({ column }) => (
          <DataGridColumnHeader title="Synced up to" column={column} />
        ),
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">
            {row.original.watermarkAt
              ? formatDateTime(row.original.watermarkAt)
              : 'Nothing synced yet'}
          </span>
        ),
        size: 170,
        enableSorting: false,
      },
      {
        id: 'initialLookbackDays',
        accessorFn: (row) => row.initialLookbackDays,
        meta: { headerTitle: 'First-run window' },
        header: ({ column }) => (
          <DataGridColumnHeader title="First-run window" column={column} />
        ),
        // The value governs the first run ONLY — once a watermark exists the
        // watermark wins. That is shown as STATE (an "In effect" / "Superseded"
        // badge paired with the "Synced up to" column) rather than explained in
        // prose, per the no-instructional-copy rule.
        cell: ({ row }) => {
          const superseded = Boolean(row.original.watermarkAt);
          return (
            <div className="flex min-w-0 flex-col items-start gap-1">
              <span
                className={
                  superseded
                    ? 'text-sm text-muted-foreground line-through'
                    : 'text-sm text-foreground'
                }
              >
                {row.original.initialLookbackDays} days
              </span>
              <Badge
                variant={superseded ? 'secondary' : 'info'}
                appearance="light"
                size="sm"
              >
                {superseded ? 'Superseded' : 'In effect'}
              </Badge>
            </div>
          );
        },
        size: 150,
        enableSorting: false,
      },
      {
        id: 'health',
        accessorFn: (row) => row.consecutiveFailures,
        meta: { headerTitle: 'Health' },
        header: ({ column }) => <DataGridColumnHeader title="Health" column={column} />,
        cell: ({ row }) => {
          const { consecutiveFailures, lastError, lastSuccessAt } = row.original;
          if (consecutiveFailures > 0) {
            return (
              <div className="flex min-w-0 flex-col items-start gap-1">
                <Badge variant="destructive" appearance="light" size="sm">
                  {consecutiveFailures} failed run
                  {consecutiveFailures === 1 ? '' : 's'}
                </Badge>
                {lastError && (
                  <ClampedText
                    text={lastError}
                    lines={2}
                    className="text-xs text-destructive"
                  />
                )}
              </div>
            );
          }
          return (
            <div className="flex items-start">
              <Badge
                variant={lastSuccessAt ? 'success' : 'secondary'}
                appearance="light"
                size="sm"
              >
                {lastSuccessAt ? 'Healthy' : 'Not yet run'}
              </Badge>
            </div>
          );
        },
        size: 210,
        enableSorting: false,
      },
      {
        // The table view renders the row `…` menu from an explicit column (the
        // shell only auto-wraps it in CARD view) — the same shape Terminology,
        // Connections and Workflows use.
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
      ...embeddedListConfig<AutocountEntityConfig>({
        viewKey: 'autocount.entities.list',
        columns,
        getRowId: (row) => row.id,
        // No per-entity detail page in slice 1 — '#' opts the list out of row
        // navigation entirely (shell contract), so a click never dead-ends.
        rowHref: () => '#',
        searchPlaceholder: 'Search entities',
        fetcher: async (query: ListQuery) => paginate(entities, query),
        actions,
      }),
      enableStatusViews: false,
    };
  }, [companyActive, entities, formatDateTime, onEditLookback, onSync]);
}
