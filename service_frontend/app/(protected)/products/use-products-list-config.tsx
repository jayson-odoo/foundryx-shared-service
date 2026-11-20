'use client';

import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Pencil, Trash2 } from 'lucide-react';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import {
  DataGridColumnHeader,
} from '@/components/ui/data-grid-column-header';
import {
  DataGridTableRowSelect,
  DataGridTableRowSelectAll,
} from '@/components/ui/data-grid-table';
import { Badge } from '@/components/ui/badge';
import type {
  ResourceAction,
  ResourceListConfig,
} from '@/components/platform/resource-list';
import { productService, type Product } from '@/services/productService';

const stop = (e: React.MouseEvent) => e.stopPropagation();

/** Money + currency, or an em dash when unpriced. */
function formatPrice(row: Product): string {
  if (row.defaultPrice == null) return '-';
  const amount = row.defaultPrice.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return row.currency ? `${row.currency} ${amount}` : amount;
}

/**
 * Products catalog list config on the shared ResourceList (SAME component as the
 * Users/Ideas lists). Columns: name, SKU, kind badge, price/currency, active.
 * Create + Edit open the shared modal (CRUD-UX standard); Delete is confirm-gated
 * via the action registry (ActionMenu renders the AlertDialog). Delete hits the
 * core `DELETE /products/{id}` (soft-delete server-side; no restore surface, so
 * the trashed view is disabled).
 */
export function useProductsListConfig(handlers: {
  onCreate: () => void;
  onEdit: (product: Product) => void;
  /**
   * No longer called by this config (fix round 1 item 12 - Delete is
   * `deferred`, so the registered `products.delete` handler commits it
   * server-side, not a frontend `run`). Kept in the signature so the caller
   * (`page.tsx`) needs no change; a future trashed-view/bulk-restore surface
   * may still want it.
   */
  onDelete: (product: Product) => Promise<void>;
}): ResourceListConfig<Product> {
  const { onCreate, onEdit } = handlers;

  return useMemo<ResourceListConfig<Product>>(() => {
    const actions: ResourceAction<Product>[] = [
      {
        id: 'edit',
        label: 'Edit',
        icon: Pencil,
        permission: 'products.update',
        surfaces: { row: true, form: true },
        run: ([product]) => {
          if (product) onEdit(product);
        },
      },
      {
        id: 'delete',
        label: 'Delete',
        icon: Trash2,
        tone: 'destructive',
        permission: 'products.delete',
        surfaces: { row: true, form: true, bulk: true },
        // Grace-window deferred action (sprint-4/23, T5, D2) - no confirm,
        // no `run` (the registered `products.delete` handler commits it).
        deferred: { actionKey: 'products.delete', entityType: 'product' },
      },
    ];

    const columns: ColumnDef<Product>[] = [
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
        id: 'name',
        accessorFn: (row) => row.name,
        meta: { headerTitle: 'Name' },
        header: ({ column }) => <DataGridColumnHeader title="Name" column={column} />,
        cell: ({ row }) => (
          <span className="truncate font-medium text-foreground" title={row.original.name}>
            {row.original.name}
          </span>
        ),
        size: 280,
        enableSorting: true,
      },
      {
        id: 'sku',
        accessorFn: (row) => row.sku ?? '',
        meta: { headerTitle: 'SKU' },
        header: ({ column }) => <DataGridColumnHeader title="SKU" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">{row.original.sku || '-'}</span>
        ),
        size: 160,
        enableSorting: true,
      },
      {
        id: 'kind',
        accessorFn: (row) => row.kindLabel ?? row.kind,
        meta: { headerTitle: 'Kind' },
        header: () => 'Kind',
        cell: ({ row }) => (
          <Badge variant="secondary" appearance="light">
            {row.original.kindLabel ?? row.original.kind}
          </Badge>
        ),
        size: 130,
        enableSorting: false,
      },
      {
        id: 'price',
        accessorFn: (row) => row.defaultPrice ?? 0,
        meta: { headerTitle: 'Price' },
        header: () => 'Price',
        cell: ({ row }) => (
          <span className="text-sm tabular-nums text-foreground">{formatPrice(row.original)}</span>
        ),
        size: 150,
        enableSorting: false,
      },
      {
        id: 'active',
        accessorFn: (row) => row.isActive,
        meta: { headerTitle: 'Status' },
        header: () => 'Status',
        cell: ({ row }) =>
          row.original.isActive ? (
            <Badge variant="success" appearance="light">
              Active
            </Badge>
          ) : (
            <Badge variant="secondary" appearance="light">
              Inactive
            </Badge>
          ),
        size: 110,
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
        size: 60,
        enableSorting: false,
        enableHiding: false,
        enableResizing: false,
      },
    ];

    return {
      viewKey: 'products.list',
      columns,
      getRowId: (p) => p.id,
      rowHref: () => '',
      // Row click opens the edit modal (no dedicated detail page).
      onRowSelect: (row) => onEdit(row),
      fetcher: (q) => productService.listProducts(q),
      exporter: (q, cols, ids) => productService.exportCsv(q, cols, ids),
      filterFields: [],
      exportColumns: [
        { id: 'id', label: 'ID' },
        { id: 'name', label: 'Name' },
        { id: 'sku', label: 'SKU' },
        { id: 'kind', label: 'Kind' },
        { id: 'defaultPrice', label: 'Price' },
        { id: 'currency', label: 'Currency' },
        { id: 'isActive', label: 'Active' },
      ],
      actions,
      searchPlaceholder: 'Search products…',
      searchHints: ['Name', 'SKU'],
      defaultSort: { id: 'name', desc: false },
      // Soft-delete has no restore route - hide the Active|Trashed toggle.
      enableStatusViews: false,
      exportFilename: 'products',
      createLabel: 'Add product',
      createPermission: 'products.create',
      onCreate,
    };
  }, [onCreate, onEdit]);
}
