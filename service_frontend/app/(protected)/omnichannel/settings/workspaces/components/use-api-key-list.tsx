'use client';

import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { KeyRound, Ban } from 'lucide-react';
import { toast } from 'sonner';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { StatusBadge } from '@/components/platform/status-badge';
import { ClampedText } from '@/components/platform/clamped-text';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import type { ResourceListConfig, ResourceAction } from '@/components/platform/resource-list';
import type { ListQuery, ListResult, FilterGroup, FilterRule } from '@/types/resource';
import { useDatetime } from '@/hooks/use-datetime';
import { apiKeysService } from '@/services/api-keys-service';
import type { ApiKeyItem } from '@/types/api-keys';
import { toCsv } from '@/lib/csv';
import { API_KEY_STATUS_REGISTRY, API_KEY_STATUS_OPTIONS } from './api-key-status';

const stop = (e: React.MouseEvent) => e.stopPropagation();

/** Walk the (small) key list client-side for the declared filter fields. */
function matchesFilter(item: ApiKeyItem, group: FilterGroup | null | undefined): boolean {
  if (!group || group.rules.length === 0) return true;
  const test = (rule: FilterRule): boolean => {
    if (rule.kind === 'group') {
      const results = rule.rules.map(test);
      return rule.combinator === 'or' ? results.some(Boolean) : results.every(Boolean);
    }
    const v = String(rule.value ?? '').toUpperCase();
    if (rule.field === 'status') {
      if (rule.operator === 'neq') return item.status !== v;
      return item.status === v;
    }
    return true;
  };
  const results = group.rules.map(test);
  return group.combinator === 'or' ? results.some(Boolean) : results.every(Boolean);
}

function sortItems(rows: ApiKeyItem[], sort: ListQuery['sort']): ApiKeyItem[] {
  if (!sort) return rows;
  const val = (i: ApiKeyItem): string => {
    switch (sort.id) {
      case 'name':
        return i.name;
      case 'status':
        return i.status;
      case 'lastUsed':
        return i.lastUsedAt ?? '';
      case 'created':
        return i.createdAt;
      default:
        return '';
    }
  };
  const sorted = [...rows].sort((a, b) => val(a).localeCompare(val(b)));
  return sort.desc ? sorted.reverse() : sorted;
}

export interface UseApiKeyListResult {
  config: ResourceListConfig<ApiKeyItem>;
}

/**
 * Workspace API-keys list config (omnichannel Slice 3) — the keys on the full
 * Resource shell embedded in the workspace detail. The key set per workspace is
 * small, so the fetcher pulls it whole and applies search/filter/sort/paginate
 * client-side (mirrors the terminology list adapter). No detail page (`rowHref`
 * '#'); Mint = the create action, Revoke = a row action.
 */
export function useApiKeyList(
  workspaceId: string,
  onMint: () => void,
): UseApiKeyListResult {
  const { formatDate, formatDateTime } = useDatetime();

  const actions = useMemo<ResourceAction<ApiKeyItem>[]>(
    () => [
      {
        id: 'revoke',
        label: 'Revoke',
        icon: Ban,
        tone: 'destructive',
        permission: 'api_keys.manage',
        surfaces: { row: true },
        isVisible: (rows) => rows.length === 1 && rows[0]?.status === 'ACTIVE',
        confirm: {
          title: 'Revoke API key?',
          description:
            'Consumers using this key will stop authenticating immediately. This cannot be undone — mint a new key to restore access.',
          confirmLabel: 'Revoke',
        },
        run: async (rows, rt) => {
          const [k] = rows;
          if (!k) return;
          try {
            await apiKeysService.revoke(workspaceId, k.id);
            toast.success('API key revoked.');
            rt.reload();
          } catch {
            toast.error('Could not revoke the key. Please retry.');
          }
        },
      },
    ],
    [workspaceId],
  );

  const config = useMemo<ResourceListConfig<ApiKeyItem>>(() => {
    const columns: ColumnDef<ApiKeyItem>[] = [
      {
        id: 'name',
        accessorFn: (r) => r.name,
        meta: { headerTitle: 'Name' },
        header: ({ column }) => <DataGridColumnHeader title="Name" column={column} />,
        cell: ({ row }) => (
          <div className="flex items-center gap-2">
            <KeyRound className="size-4 text-muted-foreground" />
            <ClampedText text={row.original.name} lines={1} className="font-medium" />
          </div>
        ),
        size: 220,
        enableSorting: true,
      },
      {
        id: 'key',
        accessorFn: (r) => r.maskedKey,
        meta: { headerTitle: 'Key' },
        header: ({ column }) => <DataGridColumnHeader title="Key" column={column} />,
        cell: ({ row }) => (
          <ClampedText
            text={row.original.maskedKey}
            lines={1}
            className="font-mono text-sm text-muted-foreground"
          />
        ),
        size: 220,
        enableSorting: false,
      },
      {
        id: 'status',
        accessorFn: (r) => r.status,
        meta: { headerTitle: 'Status' },
        header: ({ column }) => <DataGridColumnHeader title="Status" column={column} />,
        cell: ({ row }) => (
          <div className="flex items-start">
            <StatusBadge status={row.original.status} registry={API_KEY_STATUS_REGISTRY} />
          </div>
        ),
        size: 130,
        enableSorting: true,
      },
      {
        id: 'lastUsed',
        accessorFn: (r) => r.lastUsedAt,
        meta: { headerTitle: 'Last used' },
        header: ({ column }) => <DataGridColumnHeader title="Last used" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">
            {row.original.lastUsedAt ? formatDateTime(row.original.lastUsedAt) : 'Never'}
          </span>
        ),
        size: 180,
        enableSorting: true,
      },
      {
        id: 'created',
        accessorFn: (r) => r.createdAt,
        meta: { headerTitle: 'Created' },
        header: ({ column }) => <DataGridColumnHeader title="Created" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">{formatDate(row.original.createdAt)}</span>
        ),
        size: 140,
        enableSorting: true,
      },
      {
        id: 'actions',
        meta: { reorderable: false },
        header: () => null,
        cell: ({ row, table }) => {
          const meta = table.options.meta;
          const index = (meta?.pageStartIndex ?? 0) + row.index;
          return (
            <div onClick={stop} className="flex justify-end">
              <ActionMenu
                actions={actions}
                rows={[row.original]}
                runtime={{ ctx: meta?.resourceCtx, index, reload: meta?.reload ?? (() => {}) }}
                surface="row"
              />
            </div>
          );
        },
        size: 60,
        enableSorting: false,
        enableHiding: false,
        enableResizing: false,
      },
    ];

    const fetcher = async (query: ListQuery): Promise<ListResult<ApiKeyItem>> => {
      const all = await apiKeysService.list(workspaceId);
      let rows = all;
      const search = query.search?.trim().toLowerCase();
      if (search) {
        rows = rows.filter(
          (r) =>
            r.name.toLowerCase().includes(search) ||
            r.maskedKey.toLowerCase().includes(search),
        );
      }
      rows = rows.filter((r) => matchesFilter(r, query.filter));
      rows = sortItems(rows, query.sort);
      const total = rows.length;
      const start = query.page * query.pageSize;
      return { data: rows.slice(start, start + query.pageSize), total, page: query.page };
    };

    const exporter = async (query: ListQuery): Promise<string> => {
      const { data } = await fetcher({ ...query, page: 0, pageSize: 10_000 });
      return toCsv(
        ['Name', 'Key', 'Status', 'Last used', 'Created'],
        data.map((r) => [
          r.name,
          r.maskedKey,
          r.status,
          r.lastUsedAt ?? '',
          r.createdAt,
        ]),
      );
    };

    return {
      viewKey: `omnichannel.api-keys.${workspaceId}`,
      columns,
      getRowId: (k) => k.id,
      rowHref: () => '#', // no detail page
      fetcher,
      exporter,
      filterFields: [
        { field: 'status', label: 'Status', type: 'enum', options: API_KEY_STATUS_OPTIONS },
      ],
      exportColumns: [
        { id: 'name', label: 'Name' },
        { id: 'key', label: 'Key' },
        { id: 'status', label: 'Status' },
        { id: 'lastUsed', label: 'Last used' },
        { id: 'created', label: 'Created' },
      ],
      actions,
      searchPlaceholder: 'Search API keys…',
      searchHints: ['Name'],
      defaultSort: { id: 'created', desc: true },
      exportFilename: 'api-keys',
      enableStatusViews: false,
      createLabel: 'Mint key',
      createPermission: 'api_keys.manage',
      onCreate: onMint,
    };
  }, [workspaceId, actions, onMint, formatDate, formatDateTime]);

  return { config };
}
