'use client';

import { useMemo } from 'react';
import { toast } from 'sonner';
import type { ColumnDef } from '@tanstack/react-table';
import { Armchair, LayoutGrid, Pencil, Trash2 } from 'lucide-react';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { Badge } from '@/components/ui/badge';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import type { ResourceAction, ResourceListConfig } from '@/components/platform/resource-list';
import { registrationService } from '@/services/registration-service';
import { formatMoney } from '@/lib/money';
import type { ListResult } from '@/types/resource';
import type { Offering } from '@/types/registration';

const VIEW_PERM = 'offerings.read';
const EDIT_PERM = 'offerings.manage';

const stop = (e: React.MouseEvent) => e.stopPropagation();

export interface OfferingsConfigCtx {
  projectId: string;
  onCreate: () => void;
  onEdit: (row: Offering) => void;
  onViewSeats: (row: Offering) => void;
}

export function useOfferingsListConfig(ctx: OfferingsConfigCtx): ResourceListConfig<Offering> {
  const { projectId, onCreate, onEdit, onViewSeats } = ctx;

  return useMemo<ResourceListConfig<Offering>>(() => {
    const rowActions = (row: Offering, reload: () => void): ResourceAction<Offering>[] => [
      {
        id: 'edit',
        label: 'Edit',
        icon: Pencil,
        surfaces: { row: true, form: false, bulk: false },
        permission: EDIT_PERM,
        run: () => onEdit(row),
      },
      ...(row.allocationMode === 'RESERVED'
        ? [
            {
              id: 'view-seats',
              label: 'View seats',
              icon: LayoutGrid,
              surfaces: { row: true, form: false, bulk: false },
              permission: VIEW_PERM,
              run: () => onViewSeats(row),
            } as ResourceAction<Offering>,
            {
              id: 'mint',
              label: row.unitCount > 0 ? 'Re-mint seats' : 'Mint seats',
              icon: Armchair,
              surfaces: { row: true, form: false, bulk: false },
              permission: EDIT_PERM,
              run: async () => {
                try {
                  const minted = await registrationService.mintCapacityUnits(projectId, row.id);
                  toast.success(`Minted ${minted.length} seats.`);
                  reload();
                } catch (e) {
                  toast.error(e instanceof Error ? e.message : 'Could not mint.');
                }
              },
            } as ResourceAction<Offering>,
          ]
        : []),
      {
        id: 'delete',
        label: 'Delete',
        icon: Trash2,
        surfaces: { row: true, form: false, bulk: false },
        permission: EDIT_PERM,
        confirm: { title: 'Delete offering?', description: `"${row.productName}" will be removed.`, confirmLabel: 'Delete' },
        run: async () => {
          try {
            await registrationService.deleteOffering(projectId, row.id);
            reload();
          } catch (e) {
            toast.error(e instanceof Error ? e.message : 'Could not delete.');
          }
        },
      },
    ];

    const columns: ColumnDef<Offering>[] = [
      {
        id: 'product',
        accessorFn: (r) => r.productName,
        meta: { headerTitle: 'Product' },
        header: ({ column }) => <DataGridColumnHeader title="Product" column={column} />,
        cell: ({ row }) => <span className="font-medium">{row.original.productName}</span>,
        size: 200,
        enableSorting: false,
      },
      {
        id: 'mode',
        accessorFn: (r) => r.allocationMode,
        meta: { headerTitle: 'Allocation' },
        header: ({ column }) => <DataGridColumnHeader title="Allocation" column={column} />,
        cell: ({ row }) =>
          row.original.allocationMode === 'RESERVED' ? (
            <Badge variant="info" appearance="light" size="sm">Reserved</Badge>
          ) : (
            <Badge variant="secondary" appearance="light" size="sm">GA</Badge>
          ),
        size: 110,
        enableSorting: false,
      },
      {
        id: 'price',
        accessorFn: (r) => r.price,
        meta: { headerTitle: 'Price' },
        header: ({ column }) => <DataGridColumnHeader title="Price" column={column} />,
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {row.original.price == null ? 'default' : formatMoney(row.original.price, row.original.currency)}
          </span>
        ),
        size: 110,
        enableSorting: false,
      },
      {
        id: 'capacity',
        accessorFn: (r) => r.capacity,
        meta: { headerTitle: 'Capacity' },
        header: ({ column }) => <DataGridColumnHeader title="Capacity" column={column} />,
        cell: ({ row }) => {
          const o = row.original;
          const seats = o.allocationMode === 'RESERVED' ? `${o.unitCount} seats` : `${o.capacity}`;
          return <span className="text-muted-foreground">{seats}</span>;
        },
        size: 110,
        enableSorting: false,
      },
      {
        id: 'sold',
        accessorFn: (r) => r.soldCount,
        meta: { headerTitle: 'Sold / Held' },
        header: ({ column }) => <DataGridColumnHeader title="Sold / Held" column={column} />,
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {row.original.soldCount} / {row.original.heldCount}
          </span>
        ),
        size: 110,
        enableSorting: false,
      },
      {
        id: 'maxPer',
        accessorFn: (r) => r.maxTicketsPerAttendee,
        meta: { headerTitle: 'Max / attendee' },
        header: ({ column }) => <DataGridColumnHeader title="Max / attendee" column={column} />,
        cell: ({ row }) => (
          <span className="text-muted-foreground">{row.original.maxTicketsPerAttendee ?? '∞'}</span>
        ),
        size: 120,
        enableSorting: false,
      },
      {
        id: 'actions',
        meta: { reorderable: false },
        header: () => null,
        cell: ({ row, table }) => {
          const reload = table.options.meta?.reload ?? (() => {});
          return (
            <div onClick={stop} className="flex justify-end">
              <ActionMenu actions={rowActions(row.original, reload)} rows={[row.original]} runtime={{ reload }} surface="row" />
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
      viewKey: 'ems.offerings',
      getRowId: (r) => r.id,
      rowHref: () => '#', // no detail page — edit via dialog
      fetcher: async (): Promise<ListResult<Offering>> => {
        const rows = await registrationService.listOfferings(projectId);
        return { data: rows, total: rows.length, page: 0 };
      },
      exporter: async () => '',
      searchPlaceholder: 'Search offerings…',
      enableStatusViews: false,
      createLabel: 'New offering',
      createPermission: EDIT_PERM,
      onCreate,
      columns,
      filterFields: [],
      exportColumns: [],
      actions: [],
    };
  }, [projectId, onCreate, onEdit, onViewSeats]);
}
