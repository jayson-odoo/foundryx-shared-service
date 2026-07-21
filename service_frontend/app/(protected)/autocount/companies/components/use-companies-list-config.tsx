'use client';

import { useMemo } from 'react';
import { useRouter } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { Badge } from '@/components/ui/badge';
import { ClampedText } from '@/components/platform/clamped-text';
import type { ResourceListConfig } from '@/components/platform/resource-list';
import { useDatetime } from '@/hooks/use-datetime';
import { autocountService } from '@/services/autocount-service';
import type { AutocountCompany } from '@/types/autocount';
import type { ListQuery, ListResult } from '@/types/resource';
import {
  AC_COMPANIES_MANAGE,
  AC_COMPANY_NEW_PATH,
  acCompanyHref,
} from '../../components/autocount-meta';

/**
 * AutoCount companies list on the Resource shell. The backend list is
 * page-based only (no server search/sort/filter), so the fetcher passes just
 * page/pageSize — the toolbar's unsupported affordances stay off rather than
 * silently doing nothing.
 */
export function useAutocountCompaniesListConfig(): ResourceListConfig<AutocountCompany> {
  const { formatDate } = useDatetime();
  const router = useRouter();

  return useMemo<ResourceListConfig<AutocountCompany>>(() => {
    const columns: ColumnDef<AutocountCompany>[] = [
      {
        id: 'name',
        accessorFn: (row) => row.name,
        meta: { headerTitle: 'Name', reorderable: false },
        header: ({ column }) => <DataGridColumnHeader title="Name" column={column} />,
        cell: ({ row }) => (
          <div className="flex min-w-0 flex-col">
            <ClampedText
              text={row.original.name}
              lines={1}
              className="text-sm font-medium text-foreground"
            />
            <ClampedText
              text={row.original.companyName || row.original.databaseName}
              lines={1}
              className="text-xs text-muted-foreground"
            />
          </div>
        ),
        size: 260,
        enableSorting: false,
      },
      {
        id: 'databaseName',
        accessorFn: (row) => row.databaseName,
        meta: { headerTitle: 'Company database' },
        header: ({ column }) => (
          <DataGridColumnHeader title="Company database" column={column} />
        ),
        // Discovered from the login response — read-only everywhere (AC-13-01).
        cell: ({ row }) => (
          <code className="text-xs">{row.original.databaseName}</code>
        ),
        size: 220,
        enableSorting: false,
      },
      {
        id: 'status',
        accessorFn: (row) => String(row.isActive),
        meta: { headerTitle: 'Status' },
        header: ({ column }) => <DataGridColumnHeader title="Status" column={column} />,
        cell: ({ row }) => (
          <Badge
            variant={row.original.isActive ? 'success' : 'secondary'}
            appearance="light"
          >
            {row.original.isActive ? 'Active' : 'Inactive'}
          </Badge>
        ),
        size: 120,
        enableSorting: false,
      },
      {
        id: 'created',
        accessorFn: (row) => row.createdAt,
        meta: { headerTitle: 'Connected' },
        header: ({ column }) => <DataGridColumnHeader title="Connected" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">
            {row.original.createdAt ? formatDate(row.original.createdAt) : '—'}
          </span>
        ),
        size: 160,
        enableSorting: false,
      },
    ];

    return {
      viewKey: 'autocount.companies.list',
      columns,
      getRowId: (c) => c.id,
      rowHref: (c) => acCompanyHref(c.id),
      fetcher: (q: ListQuery): Promise<ListResult<AutocountCompany>> =>
        autocountService.listCompanies({ page: q.page, pageSize: q.pageSize }),
      exporter: async () => '',
      filterFields: [],
      exportColumns: [],
      actions: [],
      enableStatusViews: false,
      createLabel: 'Connect company',
      createPermission: AC_COMPANIES_MANAGE,
      onCreate: () => router.push(AC_COMPANY_NEW_PATH),
    };
  }, [formatDate, router]);
}
