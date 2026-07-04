'use client';

import { useMemo } from 'react';
import { toast } from 'sonner';
import type { ColumnDef } from '@tanstack/react-table';
import { Pencil, Power } from 'lucide-react';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import {
  DataGridTableRowSelect,
  DataGridTableRowSelectAll,
} from '@/components/ui/data-grid-table';
import { Badge } from '@/components/ui/badge';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import type { ResourceAction, ResourceListConfig } from '@/components/platform/resource-list';
import { useDatetime } from '@/hooks/use-datetime';
import { useTerminology } from '@/hooks/use-terminology';
import { emsService } from '@/services/ems-service';
import { formatMoney } from '@/lib/money';
import type { Product } from '@/types/ems';

const stop = (e: React.MouseEvent) => e.stopPropagation();

export interface ProductsConfigCtx {
  onCreate: () => void;
  onEdit: (row: Product) => void;
  categoryName: (id: string | null) => string;
}

export function useProductsListConfig(ctx: ProductsConfigCtx): ResourceListConfig<Product> {
  const { onCreate, onEdit, categoryName } = ctx;
  const { formatDateTime } = useDatetime();
  const { label, labelPlural } = useTerminology();
  const singular = label('product');
  const plural = labelPlural('product');

  return useMemo<ResourceListConfig<Product>>(() => {
    const rowActions = (row: Product, reload: () => void): ResourceAction<Product>[] => [
      {
        id: 'toggle-active',
        label: row.isActive ? 'Deactivate' : 'Activate',
        icon: Power,
        surfaces: { row: true, form: false, bulk: false },
        permission: 'products.update',
        run: async () => {
          try {
            await emsService.updateProduct(row.id, { isActive: !row.isActive });
            reload();
          } catch (e) {
            toast.error(e instanceof Error ? e.message : 'Could not update the product.');
          }
        },
      },
      {
        id: 'edit',
        label: 'Open',
        icon: Pencil,
        surfaces: { row: true, form: false, bulk: false },
        permission: 'products.read',
        run: () => onEdit(row),
      },
    ];

    const columns: ColumnDef<Product>[] = [
      {
        id: 'select',
        meta: { reorderable: false },
        header: () => <div onClick={stop}><DataGridTableRowSelectAll /></div>,
        cell: ({ row }) => <div onClick={stop}><DataGridTableRowSelect row={row} /></div>,
        size: 48,
        enableSorting: false,
        enableHiding: false,
        enableResizing: false,
      },
      {
        id: 'name',
        accessorFn: (r) => r.name,
        meta: { headerTitle: 'Name' },
        header: ({ column }) => <DataGridColumnHeader title="Name" column={column} />,
        cell: ({ row }) => <span className="font-medium">{row.original.name}</span>,
        size: 200,
        enableSorting: true,
      },
      {
        id: 'sku',
        accessorFn: (r) => r.sku,
        meta: { headerTitle: 'SKU' },
        header: ({ column }) => <DataGridColumnHeader title="SKU" column={column} />,
        cell: ({ row }) => <span className="text-muted-foreground">{row.original.sku ?? '—'}</span>,
        size: 120,
        enableSorting: true,
      },
      {
        id: 'kind',
        accessorFn: (r) => r.kind,
        meta: { headerTitle: 'Kind' },
        header: ({ column }) => <DataGridColumnHeader title="Kind" column={column} />,
        cell: ({ row }) => (
          <Badge variant="secondary" appearance="light" size="sm">
            {row.original.kindLabel || row.original.kind}
          </Badge>
        ),
        size: 130,
        enableSorting: false,
      },
      {
        id: 'category',
        accessorFn: (r) => r.categoryId,
        meta: { headerTitle: 'Category' },
        header: ({ column }) => <DataGridColumnHeader title="Category" column={column} />,
        cell: ({ row }) => (
          <span className="text-muted-foreground">{categoryName(row.original.categoryId)}</span>
        ),
        size: 150,
        enableSorting: false,
      },
      {
        id: 'defaultPrice',
        accessorFn: (r) => r.defaultPrice,
        meta: { headerTitle: 'Price' },
        header: ({ column }) => <DataGridColumnHeader title="Price" column={column} />,
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {formatMoney(row.original.defaultPrice, row.original.currency)}
          </span>
        ),
        size: 100,
        enableSorting: false,
      },
      {
        id: 'isActive',
        accessorFn: (r) => r.isActive,
        meta: { headerTitle: 'Active' },
        header: ({ column }) => <DataGridColumnHeader title="Active" column={column} />,
        cell: ({ row }) =>
          row.original.isActive ? (
            <Badge variant="success" appearance="light" size="sm">Active</Badge>
          ) : (
            <Badge variant="secondary" appearance="light" size="sm">Inactive</Badge>
          ),
        size: 100,
        enableSorting: false,
      },
      {
        id: 'createdAt',
        accessorFn: (r) => r.createdAt,
        meta: { headerTitle: 'Created' },
        header: ({ column }) => <DataGridColumnHeader title="Created" column={column} />,
        cell: ({ row }) => (
          <span className="text-muted-foreground">{formatDateTime(row.original.createdAt)}</span>
        ),
        size: 150,
        enableSorting: true,
      },
      {
        id: 'actions',
        meta: { reorderable: false },
        header: () => null,
        cell: ({ row, table }) => {
          const reload = table.options.meta?.reload ?? (() => {});
          return (
            <div onClick={stop} className="flex justify-end">
              <ActionMenu
                actions={rowActions(row.original, reload)}
                rows={[row.original]}
                runtime={{ reload }}
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

    return {
      viewKey: 'ems.products',
      getRowId: (r) => r.id,
      rowHref: (r) => `/ems/products/${r.id}`,
      fetcher: (q) => emsService.listProductsQuery(q),
      exporter: (q, cols, ids) => emsService.exportProducts(q, cols, ids),
      searchPlaceholder: `Search ${plural.toLowerCase()}…`,
      searchHints: ['Name', 'SKU'],
      defaultSort: { id: 'createdAt', desc: true },
      exportFilename: 'products',
      statusViewLabels: { active: 'Active', trashed: 'Trashed' },
      createLabel: `New ${singular.toLowerCase()}`,
      createPermission: 'products.create',
      onCreate,
      importer: { entityType: 'product', writePermission: 'products.create' },
      columns,
      filterFields: [],
      exportColumns: [
        { id: 'id', label: 'ID' },
        { id: 'name', label: 'Name' },
        { id: 'sku', label: 'SKU' },
        { id: 'kind', label: 'Kind' },
        { id: 'categoryId', label: 'Category ID' },
        { id: 'defaultPrice', label: 'Default price' },
        { id: 'tax', label: 'Tax' },
        { id: 'uom', label: 'Unit of measure' },
        { id: 'isActive', label: 'Active' },
        { id: 'createdAt', label: 'Created' },
      ],
      actions: [],
    };
  }, [formatDateTime, onCreate, onEdit, categoryName, singular, plural]);
}
