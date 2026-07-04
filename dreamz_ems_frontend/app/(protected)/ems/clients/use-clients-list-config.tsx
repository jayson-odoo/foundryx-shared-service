'use client';

import { useMemo } from 'react';
import { toast } from 'sonner';
import type { ColumnDef } from '@tanstack/react-table';
import { ArrowRight, Pencil, RefreshCw } from 'lucide-react';
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
import type { Client } from '@/types/ems';
import type { StatusNodeData, StatusTransition } from '@/types/status-engine';

const stop = (e: React.MouseEvent) => e.stopPropagation();

export interface ClientsConfigCtx {
  onCreate: () => void;
  onEdit: (row: Client) => void;
  onBulkStatus: (rows: Client[]) => void;
  statuses: StatusNodeData[];
  transitions: StatusTransition[];
}

/** Clients (B2B accounts) on the Resource shell — status (Active/Inactive/
 * Archived) shown + changed via the row "…" / bulk action; row opens the form. */
export function useClientsListConfig(ctx: ClientsConfigCtx): ResourceListConfig<Client> {
  const { onCreate, onEdit, onBulkStatus, statuses, transitions } = ctx;
  const { formatDateTime } = useDatetime();
  const { label, labelPlural } = useTerminology();
  const singular = label('client');
  const plural = labelPlural('client');

  return useMemo<ResourceListConfig<Client>>(() => {
    const statusLabel = new Map(statuses.map((s) => [s.id, s.label]));

    const rowActions = (row: Client, reload: () => void): ResourceAction<Client>[] => {
      const moves = row.statusId
        ? transitions.filter((t) => t.fromStatusId === row.statusId)
        : [];
      return [
        ...moves.map((t) => ({
          id: `move-${t.toStatusId}`,
          label: statusLabel.get(t.toStatusId) || t.label,
          icon: ArrowRight,
          surfaces: { row: true, form: false, bulk: false },
          permission: 'crm_clients.manage',
          run: async () => {
            try {
              await emsService.transitionClient(row.id, t.toStatusId);
              reload();
            } catch (e) {
              toast.error(e instanceof Error ? e.message : 'Could not change the status.');
            }
          },
        })),
        {
          id: 'edit',
          label: 'Open',
          icon: Pencil,
          surfaces: { row: true, form: false, bulk: false },
          permission: 'crm_clients.read',
          run: () => onEdit(row),
        },
      ];
    };

    const bulkActions: ResourceAction<Client>[] = [
      {
        id: 'bulk-status',
        label: 'Change status',
        icon: RefreshCw,
        surfaces: { row: false, form: false, bulk: true },
        permission: 'crm_clients.manage',
        run: (rows) => onBulkStatus(rows),
      },
    ];

    const columns: ColumnDef<Client>[] = [
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
        id: 'status',
        accessorFn: (r) => (r.statusId ? statusLabel.get(r.statusId) ?? '' : ''),
        meta: { headerTitle: 'Status' },
        header: ({ column }) => <DataGridColumnHeader title="Status" column={column} />,
        cell: ({ row }) =>
          row.original.statusId && statusLabel.get(row.original.statusId) ? (
            <Badge variant="primary" appearance="light" size="sm">
              {statusLabel.get(row.original.statusId)}
            </Badge>
          ) : (
            <span className="text-muted-foreground">—</span>
          ),
        size: 130,
        enableSorting: false,
      },
      {
        id: 'contactPerson',
        accessorFn: (r) => r.contactPerson,
        meta: { headerTitle: 'Contact' },
        header: ({ column }) => <DataGridColumnHeader title="Contact" column={column} />,
        cell: ({ row }) => (
          <span className="text-muted-foreground">{row.original.contactPerson ?? '—'}</span>
        ),
        size: 170,
        enableSorting: false,
      },
      {
        id: 'contactEmail',
        accessorFn: (r) => r.contactEmail,
        meta: { headerTitle: 'Email' },
        header: ({ column }) => <DataGridColumnHeader title="Email" column={column} />,
        cell: ({ row }) => (
          <span className="text-muted-foreground">{row.original.contactEmail ?? '—'}</span>
        ),
        size: 200,
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
      viewKey: 'ems.clients',
      getRowId: (r) => r.id,
      rowHref: (r) => `/ems/clients/${r.id}`,
      fetcher: (q) => emsService.listClientsQuery(q),
      exporter: (q, cols, ids) => emsService.exportClients(q, cols, ids),
      searchPlaceholder: `Search ${plural.toLowerCase()}…`,
      searchHints: ['Name', 'Email'],
      defaultSort: { id: 'createdAt', desc: true },
      exportFilename: 'clients',
      statusViewLabels: { active: 'Active', trashed: 'Trashed' },
      createLabel: `New ${singular.toLowerCase()}`,
      createPermission: 'crm_clients.manage',
      onCreate,
      importer: { entityType: 'client', writePermission: 'crm_clients.manage' },
      columns,
      filterFields: [],
      exportColumns: [
        { id: 'id', label: 'ID' },
        { id: 'name', label: 'Name' },
        { id: 'registrationNo', label: 'Registration no.' },
        { id: 'contactPerson', label: 'Contact person' },
        { id: 'contactEmail', label: 'Contact email' },
        { id: 'contactPhone', label: 'Contact phone' },
        { id: 'createdAt', label: 'Created' },
      ],
      actions: bulkActions,
    };
  }, [formatDateTime, onCreate, onEdit, onBulkStatus, statuses, transitions, singular, plural]);
}
