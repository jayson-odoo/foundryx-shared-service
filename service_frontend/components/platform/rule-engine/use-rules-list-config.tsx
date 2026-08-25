'use client';

/**
 * Rules observability list config (sprint-2/02 D12) - read-only: rules are
 * born where they're used; each row deep-links to its owning editor (edge
 * drawer, …). Same config-driven ResourceList shell as every other list.
 */
import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import type { RuleSiteRow } from '@/types/rules';
import { toCsv } from '@/lib/csv';
import { useDatetime } from '@/hooks/use-datetime';
import { ruleEngineService } from '@/services/rule-engine-service';
import { Badge } from '@/components/ui/badge';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { ClampedText } from '@/components/platform/clamped-text';
import type { ResourceListConfig } from '@/components/platform/resource-list/types';

/**
 * Maps a rule row's (site, target) to THIS frontend's deep-link - the
 * backend ships data, never routes (code-review fix). `statusEngineBase`
 * differs per surface: operator vs tenant settings.
 */
function editHref(row: RuleSiteRow, statusEngineBase: string): string {
  if (row.site === 'status_transition') {
    return `${statusEngineBase}/${row.target}?edit=1`;
  }
  return '#';
}

export function useRulesListConfig(
  statusEngineBase: string,
): ResourceListConfig<RuleSiteRow> {
  const { formatDateTime } = useDatetime();
  return useMemo<ResourceListConfig<RuleSiteRow>>(() => {
    const columns: ColumnDef<RuleSiteRow>[] = [
      {
        id: 'site',
        accessorFn: (row) => row.siteLabel,
        meta: { headerTitle: 'Site' },
        header: ({ column }) => (
          <DataGridColumnHeader title="Site" column={column} />
        ),
        cell: ({ row }) => (
          <Badge variant="secondary" appearance="light">
            {row.original.siteLabel}
          </Badge>
        ),
        size: 140,
        enableSorting: true,
      },
      {
        id: 'context',
        accessorFn: (row) => row.context,
        meta: { headerTitle: 'Where' },
        header: ({ column }) => (
          <DataGridColumnHeader title="Where" column={column} />
        ),
        cell: ({ row }) => (
          <span className="text-sm font-medium text-foreground">
            {row.original.context}
          </span>
        ),
        size: 220,
        enableSorting: true,
      },
      {
        id: 'summary',
        accessorFn: (row) => row.summary,
        meta: { headerTitle: 'Rule' },
        header: ({ column }) => (
          <DataGridColumnHeader title="Rule" column={column} />
        ),
        cell: ({ row }) => (
          <ClampedText
            text={row.original.summary}
            lines={2}
            className="text-xs text-muted-foreground"
          />
        ),
        size: 380,
        enableSorting: false,
      },
      {
        id: 'updated',
        accessorFn: (row) => row.updatedAt,
        meta: { headerTitle: 'Updated' },
        header: ({ column }) => (
          <DataGridColumnHeader title="Updated" column={column} />
        ),
        cell: ({ row }) => (
          <span className="text-xs text-muted-foreground">
            {formatDateTime(row.original.updatedAt)}
          </span>
        ),
        size: 140,
        enableSorting: true,
      },
    ];

    return {
      viewKey: 'rules.list',
      columns,
      getRowId: (row) => `${row.site}:${row.context}`,
      // Read-only registry - the row opens the OWNING editor (D12).
      rowHref: (row) => editHref(row, statusEngineBase),
      fetcher: (query) => ruleEngineService.listRules(query),
      exporter: async () => {
        const rows = (
          await ruleEngineService.listRules({ page: 0, pageSize: 1000 })
        ).data;
        return toCsv(
          ['Site', 'Context', 'Summary', 'Updated'],
          rows.map((r) => [r.siteLabel, r.context, r.summary, r.updatedAt]),
        );
      },
      filterFields: [],
      exportColumns: [
        { id: 'site', label: 'Site' },
        { id: 'context', label: 'Where' },
        { id: 'summary', label: 'Rule' },
        { id: 'updated', label: 'Updated' },
      ],
      actions: [],
      searchPlaceholder: 'Search rules…',
      searchHints: ['Site', 'Context', 'Rule text'],
      defaultSort: { id: 'context', desc: false },
      enableStatusViews: false,
      exportFilename: 'rules',
    };
  }, [statusEngineBase, formatDateTime]);
}
