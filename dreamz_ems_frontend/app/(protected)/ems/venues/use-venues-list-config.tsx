'use client';

import { useMemo } from 'react';
import { toast } from 'sonner';
import type { ColumnDef } from '@tanstack/react-table';
import { Pencil, Trash2 } from 'lucide-react';
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
import { registrationService } from '@/services/registration-service';
import type { Venue } from '@/types/registration';

const VIEW_PERM = 'venues.read';
const EDIT_PERM = 'venues.manage';

const stop = (e: React.MouseEvent) => e.stopPropagation();

export interface VenuesConfigCtx {
  onCreate: () => void;
  onEdit: (row: Venue) => void;
}

export function useVenuesListConfig(ctx: VenuesConfigCtx): ResourceListConfig<Venue> {
  const { onCreate, onEdit } = ctx;
  const { formatDateTime } = useDatetime();
  const { label, labelPlural } = useTerminology();
  const singular = label('venue');
  const plural = labelPlural('venue');

  return useMemo<ResourceListConfig<Venue>>(() => {
    const rowActions = (row: Venue, reload: () => void): ResourceAction<Venue>[] => [
      {
        id: 'edit',
        label: 'Open',
        icon: Pencil,
        surfaces: { row: true, form: false, bulk: false },
        permission: VIEW_PERM,
        run: () => onEdit(row),
      },
      {
        id: 'delete',
        label: 'Delete',
        icon: Trash2,
        surfaces: { row: true, form: false, bulk: false },
        permission: EDIT_PERM,
        confirm: {
          title: `Delete ${singular.toLowerCase()}?`,
          description: `"${row.name}" will be moved to Trashed.`,
          confirmLabel: 'Delete',
        },
        run: async () => {
          try {
            await registrationService.deleteVenue(row.id);
            reload();
          } catch (e) {
            toast.error(e instanceof Error ? e.message : 'Could not delete.');
          }
        },
      },
    ];

    const columns: ColumnDef<Venue>[] = [
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
        size: 220,
        enableSorting: true,
      },
      {
        id: 'address',
        accessorFn: (r) => r.address,
        meta: { headerTitle: 'Address' },
        header: ({ column }) => <DataGridColumnHeader title="Address" column={column} />,
        cell: ({ row }) => <span className="text-muted-foreground">{row.original.address || '—'}</span>,
        size: 280,
        enableSorting: false,
      },
      {
        id: 'capacity',
        accessorFn: (r) => r.capacity,
        meta: { headerTitle: 'Capacity' },
        header: ({ column }) => <DataGridColumnHeader title="Capacity" column={column} />,
        cell: ({ row }) => (
          <span className="text-muted-foreground">{row.original.capacity ?? '—'}</span>
        ),
        size: 100,
        enableSorting: false,
      },
      {
        id: 'zones',
        accessorFn: (r) => r.zoneCount,
        meta: { headerTitle: 'Zones' },
        header: ({ column }) => <DataGridColumnHeader title="Zones" column={column} />,
        cell: ({ row }) => (
          <Badge variant="secondary" appearance="light" size="sm">{row.original.zoneCount}</Badge>
        ),
        size: 90,
        enableSorting: false,
      },
      {
        id: 'seats',
        accessorFn: (r) => r.seatCount,
        meta: { headerTitle: 'Seats' },
        header: ({ column }) => <DataGridColumnHeader title="Seats" column={column} />,
        cell: ({ row }) => (
          <Badge variant="info" appearance="light" size="sm">{row.original.seatCount}</Badge>
        ),
        size: 90,
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
        size: 160,
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
      viewKey: 'ems.venues',
      getRowId: (r) => r.id,
      rowHref: (r) => `/ems/venues/${r.id}`,
      fetcher: (q) => registrationService.listVenuesQuery(q),
      exporter: () => registrationService.exportVenues(),
      searchPlaceholder: `Search ${plural.toLowerCase()}…`,
      searchHints: ['Name', 'Address'],
      defaultSort: { id: 'createdAt', desc: true },
      exportFilename: 'venues',
      statusViewLabels: { active: 'Active', trashed: 'Trashed' },
      createLabel: `New ${singular.toLowerCase()}`,
      createPermission: EDIT_PERM,
      onCreate,
      columns,
      filterFields: [],
      exportColumns: [
        { id: 'id', label: 'ID' },
        { id: 'name', label: 'Name' },
        { id: 'address', label: 'Address' },
        { id: 'capacity', label: 'Capacity' },
        { id: 'zoneCount', label: 'Zones' },
        { id: 'seatCount', label: 'Seats' },
      ],
      actions: [],
    };
  }, [formatDateTime, onCreate, onEdit, singular, plural]);
}
