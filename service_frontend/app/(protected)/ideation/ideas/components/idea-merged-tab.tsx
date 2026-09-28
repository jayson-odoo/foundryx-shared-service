'use client';

import { useMemo } from 'react';
import { LoaderCircleIcon, Split } from 'lucide-react';
import type { ColumnDef } from '@tanstack/react-table';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { ClampedText } from '@/components/platform/clamped-text';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import { ResourceList, type ResourceAction, type ResourceListConfig } from '@/components/platform/resource-list';
import { toCsv } from '@/lib/csv';
import { useIdeaMerged } from '@/hooks/use-idea-merged';
import { useIdeationRuntime } from '@/hooks/use-ideation-runtime';
import type { ListQuery, ListResult } from '@/types/resource';
import type { Idea } from '@/types/ideation';

const stop = (e: React.MouseEvent) => e.stopPropagation();

export interface IdeaMergedTabProps {
  ideaId: string;
  /** Restores the given (child) ids - the caller awaits + reloads. */
  onUnmerge: (ids: string[]) => Promise<void>;
}

/**
 * "Merged from" tab (issue #94, ideation round 2, AC-94-25) - the ideas merged
 * into this survivor, on the shared `ResourceList` (a clone of `IdeaBrsTab`).
 * Each row opens that child's own form; row and bulk Unmerge split it back
 * out.
 */
export function IdeaMergedTab({ ideaId, onUnmerge }: IdeaMergedTabProps) {
  const { merged } = useIdeaMerged(ideaId);
  // Runtime-aware href (BLOCKER 1, issue #94 review round 1) - the CRM embed
  // iframe has no operator session, so a row opened via the bare operator
  // path (`/ideation/ideas/<id>`) would break; `paths.formHref` resolves to
  // `/embed/ideas/<id>` there instead.
  const { paths } = useIdeationRuntime();

  const config = useMemo<ResourceListConfig<Idea>>(() => {
    const rows = merged ?? [];

    const actions: ResourceAction<Idea>[] = [
      {
        id: 'unmerge',
        label: 'Unmerge',
        icon: Split,
        surfaces: { row: true, form: false, bulk: true },
        isVisible: () => true,
        run: async (selected) => {
          await onUnmerge(selected.map((r) => r.id));
        },
      },
    ];

    const columns: ColumnDef<Idea>[] = [
      {
        id: 'title',
        header: () => 'Title',
        cell: ({ row }) => (
          <div className="flex items-start gap-1.5">
            <div className="min-w-0 flex-1">
              <ClampedText text={row.original.title ?? row.original.problem} lines={2} />
            </div>
            {row.original.isTest && (
              <Badge variant="secondary" appearance="light" size="sm" className="shrink-0">
                TEST
              </Badge>
            )}
          </div>
        ),
        size: 320,
        enableSorting: false,
      },
      {
        id: 'submitter',
        header: () => 'Submitter',
        cell: ({ row }) => <span className="text-muted-foreground">{row.original.submitterName}</span>,
        size: 150,
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

    const fetcher = async (query: ListQuery): Promise<ListResult<Idea>> => {
      let data = rows;
      if (query.search) {
        const s = query.search.toLowerCase();
        data = data.filter(
          (r) =>
            (r.title ?? r.problem).toLowerCase().includes(s) ||
            r.problem.toLowerCase().includes(s) ||
            r.submitterName.toLowerCase().includes(s),
        );
      }
      const total = data.length;
      const start = query.page * query.pageSize;
      return { data: data.slice(start, start + query.pageSize), total, page: query.page };
    };

    const exporter = async (query: ListQuery): Promise<string> => {
      const { data } = await fetcher({ ...query, page: 0, pageSize: 10_000 });
      return toCsv(['Title', 'Submitter'], data.map((r) => [r.title ?? r.problem, r.submitterName]));
    };

    return {
      viewKey: 'ideation.idea.merged',
      getRowId: (row) => row.id,
      rowHref: (row) => paths.formHref(row.id),
      fetcher,
      exporter,
      searchPlaceholder: 'Search merged ideas…',
      searchHints: ['Title', 'Submitter'],
      // Lineage list - no Active/Trashed segmentation (there is no trashed view).
      enableStatusViews: false,
      columns,
      filterFields: [],
      exportColumns: [
        { id: 'title', label: 'Title' },
        { id: 'submitter', label: 'Submitter' },
      ],
      actions,
    };
  }, [merged, onUnmerge, paths]);

  if (merged === null) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-12 text-muted-foreground">
          <LoaderCircleIcon className="size-5 animate-spin" />
        </CardContent>
      </Card>
    );
  }

  if (merged.length === 0) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-sm text-muted-foreground">
          No merged ideas.
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
