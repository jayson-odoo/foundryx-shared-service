'use client';

import { useMemo } from 'react';
import { toast } from 'sonner';
import type { ColumnDef } from '@tanstack/react-table';
import { ArrowRight, Copy, Pencil } from 'lucide-react';
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
import type { Quotation } from '@/types/ems';
import type { StatusNodeData, StatusTransition } from '@/types/status-engine';

const stop = (e: React.MouseEvent) => e.stopPropagation();

export interface QuotationsConfigCtx {
  onCreate: () => void;
  onEdit: (row: Quotation) => void;
  clientName: (id: string) => string;
  statuses: StatusNodeData[];
  transitions: StatusTransition[];
}

export function useQuotationsListConfig(ctx: QuotationsConfigCtx): ResourceListConfig<Quotation> {
  const { onCreate, onEdit, clientName, statuses, transitions } = ctx;
  const { formatDateTime } = useDatetime();
  const { label, labelPlural } = useTerminology();
  const singular = label('quotation');
  const plural = labelPlural('quotation');

  return useMemo<ResourceListConfig<Quotation>>(() => {
    const statusLabel = new Map(statuses.map((s) => [s.id, s.label]));

    const rowActions = (row: Quotation, reload: () => void): ResourceAction<Quotation>[] => {
      const moves = row.statusId ? transitions.filter((t) => t.fromStatusId === row.statusId) : [];
      return [
        ...moves.map((t) => ({
          id: `move-${t.toStatusId}`,
          label: statusLabel.get(t.toStatusId) || t.label,
          icon: ArrowRight,
          surfaces: { row: true, form: false, bulk: false },
          permission: 'crm_quotations.manage',
          run: async () => {
            try {
              await emsService.transitionQuotation(row.id, t.toStatusId);
              reload();
            } catch (e) {
              toast.error(e instanceof Error ? e.message : 'Could not change the status.');
            }
          },
        })),
        {
          id: 'revise',
          label: 'Revise',
          icon: Copy,
          surfaces: { row: true, form: false, bulk: false },
          permission: 'crm_quotations.manage',
          run: async () => {
            try {
              const rev = await emsService.reviseQuotation(row.id);
              toast.success(`Revision ${rev.revisionNumber} created.`);
              onEdit(rev);
            } catch (e) {
              toast.error(e instanceof Error ? e.message : 'Could not revise.');
            }
          },
        },
        {
          id: 'edit',
          label: 'Open',
          icon: Pencil,
          surfaces: { row: true, form: false, bulk: false },
          permission: 'crm_quotations.read',
          run: () => onEdit(row),
        },
      ];
    };

    const columns: ColumnDef<Quotation>[] = [
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
        id: 'client',
        accessorFn: (r) => r.clientId,
        meta: { headerTitle: 'Client' },
        header: ({ column }) => <DataGridColumnHeader title="Client" column={column} />,
        cell: ({ row }) => <span className="font-medium">{clientName(row.original.clientId)}</span>,
        size: 220,
        enableSorting: false,
      },
      {
        id: 'revisionNumber',
        accessorFn: (r) => r.revisionNumber,
        meta: { headerTitle: 'Rev' },
        header: ({ column }) => <DataGridColumnHeader title="Rev" column={column} />,
        cell: ({ row }) => <span className="text-muted-foreground">v{row.original.revisionNumber}</span>,
        size: 70,
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
        size: 120,
        enableSorting: false,
      },
      {
        id: 'total',
        accessorFn: (r) => r.total,
        meta: { headerTitle: 'Total' },
        header: ({ column }) => <DataGridColumnHeader title="Total" column={column} />,
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {row.original.currency ? `${row.original.currency} ` : ''}
            {row.original.total}
          </span>
        ),
        size: 120,
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
      viewKey: 'ems.quotations',
      getRowId: (r) => r.id,
      rowHref: (r) => `/ems/quotations/${r.id}`,
      fetcher: (q) => emsService.listQuotationsQuery(q),
      exporter: (q, cols, ids) => emsService.exportQuotations(q, cols, ids),
      searchPlaceholder: `Search ${plural.toLowerCase()}…`,
      defaultSort: { id: 'createdAt', desc: true },
      exportFilename: 'quotations',
      statusViewLabels: { active: 'Active', trashed: 'Trashed' },
      createLabel: `New ${singular.toLowerCase()}`,
      createPermission: 'crm_quotations.manage',
      onCreate,
      columns,
      filterFields: [],
      exportColumns: [
        { id: 'id', label: 'ID' },
        { id: 'clientId', label: 'Client ID' },
        { id: 'leadId', label: 'Lead ID' },
        { id: 'projectId', label: 'Event ID' },
        { id: 'revisionNumber', label: 'Revision' },
        { id: 'currency', label: 'Currency' },
        { id: 'total', label: 'Total' },
        { id: 'createdAt', label: 'Created' },
      ],
      actions: [],
    };
  }, [formatDateTime, onCreate, onEdit, clientName, statuses, transitions, singular, plural]);
}
