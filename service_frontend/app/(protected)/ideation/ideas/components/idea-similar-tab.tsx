'use client';

import { useMemo } from 'react';
import { GitMerge, LoaderCircleIcon } from 'lucide-react';
import type { ColumnDef } from '@tanstack/react-table';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { ClampedText } from '@/components/platform/clamped-text';
import { StatusBadge } from '@/components/platform/status-badge';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import { ResourceList, type ResourceAction, type ResourceListConfig } from '@/components/platform/resource-list';
import {
  DataGridTableRowSelect,
  DataGridTableRowSelectAll,
} from '@/components/ui/data-grid-table';
import { toCsv } from '@/lib/csv';
import { useIdeaSimilar } from '@/hooks/use-idea-similar';
import { useIdeationRuntime } from '@/hooks/use-ideation-runtime';
import type { ListQuery, ListResult } from '@/types/resource';
import type { Idea } from '@/types/ideation';
import { statusRegistryFor } from './status-registry';

const stop = (e: React.MouseEvent) => e.stopPropagation();

export interface IdeaSimilarTabProps {
  ideaId: string;
  /** Opens the merge dialog with the current idea + these rows. */
  onMerge: (rows: Idea[]) => void;
}

/**
 * Similar ideas tab (plan 20, AC-20-23) - AI-ranked ideas on the same product,
 * on the shared `ResourceList` (a clone of `IdeaMergedTab`). Row "..." Merge and
 * bulk Actions > Merge open the field-level merge dialog. When the AI could not
 * rank, the tab says so and offers Retry (no word-match fallback).
 */
export function IdeaSimilarTab({ ideaId, onMerge }: IdeaSimilarTabProps) {
  const { state, retry } = useIdeaSimilar(ideaId);
  const { paths, mode } = useIdeationRuntime();
  const rows = state.status === 'ready' ? state.ideas : [];

  const config = useMemo<ResourceListConfig<Idea>>(() => {
    const actions: ResourceAction<Idea>[] = [
      {
        id: 'merge',
        label: 'Merge',
        icon: GitMerge,
        permission: mode === 'operator' ? 'ideation.triage.manage' : undefined,
        surfaces: { row: true, form: false, bulk: true },
        isVisible: (selected) => selected.length > 0 && selected.every((r) => !r.statusIsArchived),
        run: async (selected) => {
          onMerge(selected);
        },
      },
    ];

    const columns: ColumnDef<Idea>[] = [
      {
        id: 'select',
        meta: { reorderable: false },
        header: () => (
          <div onClick={stop}>
            <DataGridTableRowSelectAll />
          </div>
        ),
        cell: ({ row }) => (
          <div onClick={stop}>
            <DataGridTableRowSelect row={row} />
          </div>
        ),
        size: 48,
        enableSorting: false,
        enableHiding: false,
        enableResizing: false,
      },
      {
        id: 'number',
        meta: { headerTitle: 'Idea' },
        header: () => 'Idea',
        cell: ({ row }) => (
          <span className="font-medium text-primary">{row.original.ideaNumber ?? '-'}</span>
        ),
        size: 110,
        enableSorting: false,
      },
      {
        id: 'title',
        meta: { headerTitle: 'Title' },
        header: () => 'Title',
        cell: ({ row }) => <ClampedText text={row.original.title ?? row.original.problem} lines={2} />,
        size: 320,
        enableSorting: false,
      },
      {
        id: 'status',
        meta: { headerTitle: 'Status' },
        header: () => 'Status',
        cell: ({ row }) => (
          <StatusBadge status={row.original.status} registry={statusRegistryFor(row.original)} />
        ),
        size: 130,
        enableSorting: false,
      },
      {
        id: 'votes',
        meta: { headerTitle: 'Votes' },
        header: () => 'Votes',
        cell: ({ row }) => <span className="tabular-nums">{row.original.upvotes}</span>,
        size: 80,
        enableSorting: false,
      },
      {
        id: 'actions',
        meta: { reorderable: false },
        header: () => null,
        cell: ({ row, table }) => (
          <div onClick={stop} className="flex justify-end">
            <ActionMenu
              actions={actions}
              rows={[row.original]}
              runtime={{ reload: table.options.meta?.reload ?? (() => {}) }}
              surface="row"
            />
          </div>
        ),
        size: 56,
        enableSorting: false,
        enableHiding: false,
        enableResizing: false,
      },
    ];

    // Keep the AI ranking order; search narrows it client side.
    const fetcher = async (query: ListQuery): Promise<ListResult<Idea>> => {
      let data = rows;
      if (query.search) {
        const s = query.search.toLowerCase();
        data = data.filter(
          (r) =>
            (r.title ?? r.problem).toLowerCase().includes(s) ||
            (r.ideaNumber ?? '').toLowerCase().includes(s),
        );
      }
      const total = data.length;
      const start = query.page * query.pageSize;
      return { data: data.slice(start, start + query.pageSize), total, page: query.page };
    };

    const exporter = async (query: ListQuery): Promise<string> => {
      const { data } = await fetcher({ ...query, page: 0, pageSize: 10_000 });
      return toCsv(
        ['Idea', 'Title', 'Status', 'Votes'],
        data.map((r) => [r.ideaNumber ?? '', r.title ?? r.problem, r.statusLabel ?? r.status, String(r.upvotes)]),
      );
    };

    return {
      viewKey: 'ideation.idea.similar',
      getRowId: (row) => row.id,
      rowHref: (row) => paths.formHref(row.id),
      fetcher,
      exporter,
      searchPlaceholder: 'Search similar ideas…',
      searchHints: ['Idea', 'Title'],
      enableStatusViews: false,
      columns,
      filterFields: [],
      exportColumns: [
        { id: 'number', label: 'Idea' },
        { id: 'title', label: 'Title' },
        { id: 'status', label: 'Status' },
        { id: 'votes', label: 'Votes' },
      ],
      actions,
    };
  }, [rows, onMerge, paths, mode]);

  if (state.status === 'loading') {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-12 text-muted-foreground">
          <LoaderCircleIcon className="size-5 animate-spin" aria-label="Finding similar ideas" />
        </CardContent>
      </Card>
    );
  }

  if (state.status === 'unavailable') {
    return (
      <Card>
        <CardContent className="flex flex-col items-center gap-3 py-8 text-center">
          <p className="text-sm text-muted-foreground">Similar ideas unavailable</p>
          <Button variant="outline" size="sm" onClick={retry}>
            Retry
          </Button>
        </CardContent>
      </Card>
    );
  }

  if (rows.length === 0) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-sm text-muted-foreground">
          No similar ideas
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardContent className="py-4">
        <ResourceList config={config} hideHeader />
      </CardContent>
    </Card>
  );
}
