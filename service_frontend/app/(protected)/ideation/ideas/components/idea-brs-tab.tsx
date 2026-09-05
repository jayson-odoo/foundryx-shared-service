'use client';

import { useMemo } from 'react';
import { LoaderCircleIcon } from 'lucide-react';
import type { ColumnDef } from '@tanstack/react-table';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { ClampedText } from '@/components/platform/clamped-text';
import { ResourceList, type ResourceListConfig } from '@/components/platform/resource-list';
import { toCsv } from '@/lib/csv';
import { useIdeaBusinessRequirements } from '@/hooks/use-idea-business-requirements';
import type { ListQuery, ListResult } from '@/types/resource';
import type { BusinessRequirement } from '@/types/business-requirement';
import { brFormHref } from '../../business-requirements/components/paths';

export interface IdeaBrsTabProps {
  ideaId: string;
}

/**
 * Business Requirements tab (AC-BI-29c) - the BRs this idea feeds, on the shared
 * ResourceList (NOT a hand-rolled list, matching the BR ↔ Ideas reverse). Each
 * row navigates to the BR detail. Read-only lineage - link/unlink lives on the
 * BR's own Ideas tab.
 */
export function IdeaBrsTab({ ideaId }: IdeaBrsTabProps) {
  const { brs } = useIdeaBusinessRequirements(ideaId);

  const config = useMemo<ResourceListConfig<BusinessRequirement>>(() => {
    const rows = brs ?? [];
    const columns: ColumnDef<BusinessRequirement>[] = [
      {
        id: 'title',
        header: () => 'Title',
        cell: ({ row }) => (
          <ClampedText text={row.original.title || 'Untitled BR'} lines={2} />
        ),
        size: 320,
        enableSorting: false,
      },
      {
        id: 'product',
        header: () => 'Product',
        cell: ({ row }) => <Badge variant="secondary">{row.original.productName}</Badge>,
        size: 150,
        enableSorting: false,
      },
      {
        id: 'status',
        header: () => 'Status',
        cell: ({ row }) => (
          <Badge variant="outline" appearance="light">
            {row.original.statusLabel}
          </Badge>
        ),
        size: 120,
        enableSorting: false,
      },
    ];

    const fetcher = async (
      query: ListQuery,
    ): Promise<ListResult<BusinessRequirement>> => {
      let data = rows;
      if (query.search) {
        const s = query.search.toLowerCase();
        data = data.filter(
          (r) =>
            r.title.toLowerCase().includes(s) ||
            r.productName.toLowerCase().includes(s),
        );
      }
      const total = data.length;
      const start = query.page * query.pageSize;
      return { data: data.slice(start, start + query.pageSize), total, page: query.page };
    };

    const exporter = async (query: ListQuery): Promise<string> => {
      const { data } = await fetcher({ ...query, page: 0, pageSize: 10_000 });
      return toCsv(
        ['Title', 'Product', 'Status'],
        data.map((r) => [r.title, r.productName, r.statusLabel]),
      );
    };

    return {
      viewKey: 'ideation.idea.business_requirements',
      getRowId: (row) => row.id,
      rowHref: (row) => brFormHref(row.id),
      fetcher,
      exporter,
      searchPlaceholder: 'Search requirements…',
      searchHints: ['Title', 'Product'],
      // Lineage list - no Active/Trashed segmentation (there is no trashed view).
      enableStatusViews: false,
      columns,
      filterFields: [],
      exportColumns: [
        { id: 'title', label: 'Title' },
        { id: 'product', label: 'Product' },
        { id: 'status', label: 'Status' },
      ],
      actions: [],
    };
  }, [brs]);

  if (brs === null) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-12 text-muted-foreground">
          <LoaderCircleIcon className="size-5 animate-spin" />
        </CardContent>
      </Card>
    );
  }

  if (brs.length === 0) {
    return (
      <Card>
        <CardContent className="py-8 text-center text-sm text-muted-foreground">
          This idea has not been promoted to a business requirement yet.
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
