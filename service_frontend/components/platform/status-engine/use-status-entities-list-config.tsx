'use client';

/**
 * Entity ResourceList config (sprint-2/01 rework) - the status engine's list
 * surface follows the same config-driven shell as Users/Tenants. The registry
 * is small + code-side, so the fetcher adapts the full entity list to the
 * shell's server-query contract client-side (search/sort/page).
 */
import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import type { ListQuery, ListResult } from '@/types/resource';
import type { StatusEntity } from '@/types/status-engine';
import { toCsv } from '@/lib/csv';
import { statusEngineService } from '@/services/status-engine-service';
import { Badge } from '@/components/ui/badge';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import type { ResourceListConfig } from '@/components/platform/resource-list/types';

function applyQuery(
  entities: StatusEntity[],
  query: ListQuery,
): ListResult<StatusEntity> {
  let rows = entities;
  const term = query.search?.trim().toLowerCase();
  if (term) {
    rows = rows.filter(
      (e) =>
        e.label.toLowerCase().includes(term) ||
        e.entityType.toLowerCase().includes(term) ||
        e.module.toLowerCase().includes(term),
    );
  }
  const sortField = query.sort?.id ?? 'entity';
  const dir = query.sort?.desc ? -1 : 1;
  rows = [...rows].sort((a, b) => {
    const value = (row: StatusEntity) => {
      switch (sortField) {
        case 'module':
          return row.module;
        case 'statuses':
          return row.statusCount;
        case 'transitions':
          return row.transitionCount;
        default:
          return row.label;
      }
    };
    const va = value(a);
    const vb = value(b);
    return (
      (typeof va === 'number' && typeof vb === 'number'
        ? va - vb
        : String(va).localeCompare(String(vb))) * dir
    );
  });
  const start = query.page * query.pageSize;
  return {
    data: rows.slice(start, start + query.pageSize),
    total: rows.length,
    page: query.page,
  };
}

function entitiesCsv(entities: StatusEntity[]): string {
  return toCsv(
    ['Entity', 'Module', 'Statuses', 'Transitions', 'Source'],
    entities.map((e) => [
      e.label,
      e.module,
      e.statusCount,
      e.transitionCount,
      e.customized ? 'Customized' : 'Platform defaults',
    ]),
  );
}

export function useStatusEntitiesListConfig(
  basePath: string,
): ResourceListConfig<StatusEntity> {
  return useMemo<ResourceListConfig<StatusEntity>>(() => {
    const columns: ColumnDef<StatusEntity>[] = [
      {
        id: 'entity',
        accessorFn: (row) => row.label,
        meta: { headerTitle: 'Entity' },
        header: ({ column }) => (
          <DataGridColumnHeader title="Entity" column={column} />
        ),
        cell: ({ row }) => (
          <div className="flex flex-col leading-tight">
            <span className="text-sm font-medium text-foreground">
              {row.original.label}
            </span>
            <span className="font-mono text-xs text-muted-foreground">
              {row.original.entityType}
            </span>
          </div>
        ),
        size: 220,
        enableSorting: true,
      },
      {
        id: 'module',
        accessorFn: (row) => row.module,
        meta: { headerTitle: 'Module' },
        header: ({ column }) => (
          <DataGridColumnHeader title="Module" column={column} />
        ),
        cell: ({ row }) => (
          <Badge variant="secondary" appearance="light">
            {row.original.module}
          </Badge>
        ),
        size: 120,
        enableSorting: true,
      },
      {
        id: 'statuses',
        accessorFn: (row) => row.statusCount,
        meta: { headerTitle: 'Statuses' },
        header: ({ column }) => (
          <DataGridColumnHeader title="Statuses" column={column} />
        ),
        cell: ({ row }) => (
          <span className="tabular-nums">{row.original.statusCount}</span>
        ),
        size: 100,
        enableSorting: true,
      },
      {
        id: 'transitions',
        accessorFn: (row) => row.transitionCount,
        meta: { headerTitle: 'Transitions' },
        header: ({ column }) => (
          <DataGridColumnHeader title="Transitions" column={column} />
        ),
        cell: ({ row }) => (
          <span className="tabular-nums">{row.original.transitionCount}</span>
        ),
        size: 110,
        enableSorting: true,
      },
      {
        id: 'source',
        accessorFn: (row) => row.customized,
        meta: { headerTitle: 'Source' },
        header: ({ column }) => (
          <DataGridColumnHeader title="Source" column={column} />
        ),
        cell: ({ row }) => (
          <Badge
            variant={row.original.customized ? 'primary' : 'secondary'}
            appearance="light"
          >
            {row.original.customized ? 'Customized' : 'Platform defaults'}
          </Badge>
        ),
        size: 150,
        enableSorting: false,
      },
    ];

    return {
      viewKey: 'statusEntities.list',
      columns,
      getRowId: (row) => row.entityType,
      rowHref: (row) => `${basePath}/${row.entityType}`,
      fetcher: async (query) =>
        applyQuery(await statusEngineService.entities(), query),
      exporter: async () => entitiesCsv(await statusEngineService.entities()),
      filterFields: [],
      exportColumns: [
        { id: 'entity', label: 'Entity' },
        { id: 'module', label: 'Module' },
        { id: 'statuses', label: 'Statuses' },
        { id: 'transitions', label: 'Transitions' },
        { id: 'source', label: 'Source' },
      ],
      actions: [],
      searchPlaceholder: 'Search entities…',
      searchHints: ['Entity', 'Module'],
      defaultSort: { id: 'entity', desc: false },
      enableStatusViews: false,
      exportFilename: 'status-entities',
    };
  }, [basePath]);
}
