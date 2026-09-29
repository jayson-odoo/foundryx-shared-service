'use client';

import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { ClampedText } from '@/components/platform/clamped-text';
import { StatusBadge } from '@/components/platform/status-badge';
import { embeddedListConfig } from '@/components/platform/resource-list/embedded-list-config';
import type { ResourceListConfig } from '@/components/platform/resource-list';
import { useDatetime } from '@/hooks/use-datetime';
import { autocountService } from '@/services/autocount-service';
import type { DocFeedIssue, DocFeedIssueKind, DocFeedKey } from '@/types/autocount';
import type { FilterGroup, ListQuery } from '@/types/resource';
import { AC_DOC_FEED_ISSUE_KIND_REGISTRY, AC_DOC_FEED_KEYS, docFeedLabel } from '../../components/autocount-meta';

/** Mirrors `use-staged-list-config.tsx`'s own `readEq`. */
function readEq(filter: FilterGroup | null | undefined, field: string): string | undefined {
  const rule = filter?.rules.find((r) => r.kind === 'condition' && r.field === field);
  return rule && rule.kind === 'condition' && typeof rule.value === 'string' ? rule.value : undefined;
}

/** `{field: message}` pairs, one per line (AC-14-83's "errors (ClampedText,
 * field: message pairs)") - the CRM's own error map, never re-worded. */
function errorsText(errors: Record<string, unknown> | null): string {
  if (!errors) return '-';
  const entries = Object.entries(errors);
  if (entries.length === 0) return '-';
  return entries.map(([field, message]) => `${field}: ${String(message)}`).join('; ');
}

/**
 * Document feed issues - the documents the CRM did not take (AC-14-71, 94).
 * Kind and feed filters, DocNo search through the shell's own always-on
 * search box (wired to `search` on the fetcher, same as every other list).
 */
export function useDocFeedIssuesListConfig(companyId: string): ResourceListConfig<DocFeedIssue> {
  const { formatDateTime } = useDatetime();

  return useMemo<ResourceListConfig<DocFeedIssue>>(() => {
    const columns: ColumnDef<DocFeedIssue>[] = [
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
        id: 'docNo',
        accessorFn: (row) => row.docNo ?? '',
        meta: { headerTitle: 'Doc no' },
        header: ({ column }) => <DataGridColumnHeader title="Doc no" column={column} />,
        cell: ({ row }) => <span className="text-sm text-foreground">{row.original.docNo ?? '-'}</span>,
        size: 140,
        enableSorting: false,
      },
      {
        id: 'docDate',
        accessorFn: (row) => row.docDate ?? '',
        meta: { headerTitle: 'Doc date' },
        header: ({ column }) => <DataGridColumnHeader title="Doc date" column={column} />,
        cell: ({ row }) => <span className="text-sm text-muted-foreground">{row.original.docDate ?? '-'}</span>,
        size: 120,
        enableSorting: false,
      },
      {
        id: 'kind',
        accessorFn: (row) => row.kind,
        meta: { headerTitle: 'Kind' },
        header: ({ column }) => <DataGridColumnHeader title="Kind" column={column} />,
        cell: ({ row }) => (
          <StatusBadge
            status={row.original.kind as DocFeedIssueKind}
            registry={AC_DOC_FEED_ISSUE_KIND_REGISTRY}
            size="sm"
          />
        ),
        size: 110,
        enableSorting: false,
      },
      {
        id: 'errors',
        accessorFn: (row) => errorsText(row.errors),
        meta: { headerTitle: 'Errors' },
        header: ({ column }) => <DataGridColumnHeader title="Errors" column={column} />,
        cell: ({ row }) => (
          <ClampedText text={errorsText(row.original.errors)} lines={2} className="text-sm text-destructive" />
        ),
        size: 320,
        enableSorting: false,
      },
      {
        id: 'attempts',
        accessorFn: (row) => row.attempts,
        meta: { headerTitle: 'Attempts' },
        header: ({ column }) => <DataGridColumnHeader title="Attempts" column={column} />,
        cell: ({ row }) => <span className="text-sm tabular-nums text-muted-foreground">{row.original.attempts}</span>,
        size: 90,
        enableSorting: false,
      },
      {
        id: 'lastAt',
        accessorFn: (row) => row.lastAt ?? '',
        meta: { headerTitle: 'Last attempt' },
        header: ({ column }) => <DataGridColumnHeader title="Last attempt" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">
            {row.original.lastAt ? formatDateTime(row.original.lastAt) : '-'}
          </span>
        ),
        size: 170,
        enableSorting: false,
      },
    ];

    return {
      ...embeddedListConfig<DocFeedIssue>({
        viewKey: 'autocount.doc-feed-issues.list',
        columns,
        getRowId: (r) => `${r.feed}:${r.book}:${r.docKey}`,
        rowHref: () => '#',
        searchPlaceholder: 'Search Doc no',
        fetcher: (query: ListQuery) =>
          autocountService.listDocFeedIssues(companyId, {
            page: query.page,
            pageSize: query.pageSize,
            feed: readEq(query.filter, 'feed') as DocFeedKey | undefined,
            kind: readEq(query.filter, 'kind') as 'retryable' | 'failed' | undefined,
            search: query.search,
          }),
      }),
      filterFields: [
        {
          field: 'kind',
          label: 'Kind',
          type: 'enum',
          options: [
            { label: 'Waiting', value: 'retryable' },
            { label: 'Failed', value: 'failed' },
          ],
        },
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
