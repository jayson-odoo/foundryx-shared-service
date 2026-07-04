'use client';

import { useMemo } from 'react';
import { toast } from 'sonner';
import type { ColumnDef } from '@tanstack/react-table';
import { ArrowRight, CalendarPlus, Pencil, RefreshCw } from 'lucide-react';
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
import type { Lead } from '@/types/ems';
import type { StatusNodeData, StatusTransition } from '@/types/status-engine';

const stop = (e: React.MouseEvent) => e.stopPropagation();

export interface LeadsConfigCtx {
  onCreate: () => void;
  onEdit: (row: Lead) => void;
  onBulkStatus: (rows: Lead[]) => void;
  /** Won → open the "Create event" template-picker dialog (graph-driven). */
  onConvert: (row: Lead) => void;
  statuses: StatusNodeData[];
  transitions: StatusTransition[];
}

export function useLeadsListConfig(ctx: LeadsConfigCtx): ResourceListConfig<Lead> {
  const { onCreate, onEdit, onBulkStatus, onConvert, statuses, transitions } = ctx;
  const { formatDateTime } = useDatetime();
  const { label, labelPlural } = useTerminology();
  const singular = label('lead');
  const plural = labelPlural('lead');

  return useMemo<ResourceListConfig<Lead>>(() => {
    const statusLabel = new Map(statuses.map((s) => [s.id, s.label]));
    const wonId = statuses.find((s) => s.key === 'won')?.id;

    const rowActions = (row: Lead, reload: () => void): ResourceAction<Lead>[] => {
      // Win is a PLAIN status move now (every outgoing edge shows by its target's
      // bare name). Creating an event is a SEPARATE, repeatable action on a Won
      // lead (decision sprint-4/08) — needs the Events module (else 409).
      const moves = row.statusId ? transitions.filter((t) => t.fromStatusId === row.statusId) : [];
      const isWon = !!wonId && row.statusId === wonId;
      return [
        ...(isWon
          ? [
              {
                id: 'create-event',
                label: 'Create event',
                icon: CalendarPlus,
                surfaces: { row: true, form: false, bulk: false },
                permission: 'crm_leads.manage',
                run: () => onConvert(row),
              } as ResourceAction<Lead>,
            ]
          : []),
        ...moves.map((t) => ({
          id: `move-${t.toStatusId}`,
          label: statusLabel.get(t.toStatusId) || t.label,
          icon: ArrowRight,
          surfaces: { row: true, form: false, bulk: false },
          permission: 'crm_leads.manage',
          run: async () => {
            try {
              await emsService.transitionLead(row.id, t.toStatusId);
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
          permission: 'crm_leads.read',
          run: () => onEdit(row),
        },
      ];
    };

    const bulkActions: ResourceAction<Lead>[] = [
      {
        id: 'bulk-status',
        label: 'Change status',
        icon: RefreshCw,
        surfaces: { row: false, form: false, bulk: true },
        permission: 'crm_leads.manage',
        run: (rows) => onBulkStatus(rows),
      },
    ];

    const columns: ColumnDef<Lead>[] = [
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
        id: 'title',
        accessorFn: (r) => r.title,
        meta: { headerTitle: 'Title' },
        header: ({ column }) => <DataGridColumnHeader title="Title" column={column} />,
        cell: ({ row }) => <span className="font-medium">{row.original.title}</span>,
        size: 240,
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
        id: 'source',
        accessorFn: (r) => r.source,
        meta: { headerTitle: 'Source' },
        header: ({ column }) => <DataGridColumnHeader title="Source" column={column} />,
        cell: ({ row }) => (
          <span className="text-muted-foreground">{row.original.source ?? '—'}</span>
        ),
        size: 150,
        enableSorting: true,
      },
      {
        id: 'contactName',
        accessorFn: (r) => r.contactName,
        meta: { headerTitle: 'Contact' },
        header: ({ column }) => <DataGridColumnHeader title="Contact" column={column} />,
        cell: ({ row }) => (
          <span className="text-muted-foreground">{row.original.contactName ?? '—'}</span>
        ),
        size: 160,
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
      viewKey: 'ems.leads',
      getRowId: (r) => r.id,
      rowHref: (r) => `/ems/leads/${r.id}`,
      fetcher: (q) => emsService.listLeadsQuery(q),
      exporter: (q, cols, ids) => emsService.exportLeads(q, cols, ids),
      searchPlaceholder: `Search ${plural.toLowerCase()}…`,
      searchHints: ['Title', 'Contact'],
      defaultSort: { id: 'createdAt', desc: true },
      exportFilename: 'leads',
      statusViewLabels: { active: 'Active', trashed: 'Trashed' },
      createLabel: `New ${singular.toLowerCase()}`,
      createPermission: 'crm_leads.manage',
      onCreate,
      importer: { entityType: 'lead', writePermission: 'crm_leads.manage' },
      columns,
      filterFields: [],
      exportColumns: [
        { id: 'id', label: 'ID' },
        { id: 'title', label: 'Title' },
        { id: 'clientId', label: 'Client ID' },
        { id: 'source', label: 'Source' },
        { id: 'contactName', label: 'Contact name' },
        { id: 'contactEmail', label: 'Contact email' },
        { id: 'contactPhone', label: 'Contact phone' },
        { id: 'createdAt', label: 'Created' },
      ],
      actions: bulkActions,
    };
  }, [formatDateTime, onCreate, onEdit, onBulkStatus, onConvert, statuses, transitions, singular, plural]);
}
