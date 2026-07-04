'use client';

import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { FileText, Pencil, Send, Trash2, Code2 } from 'lucide-react';
import { toast } from 'sonner';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import {
  DataGridTableRowSelect,
  DataGridTableRowSelectAll,
} from '@/components/ui/data-grid-table';
import { StatusBadge } from '@/components/platform/status-badge';
import { ClampedText } from '@/components/platform/clamped-text';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import type { ResourceListConfig, ResourceAction } from '@/components/platform/resource-list';
import type { ListQuery } from '@/types/resource';
import type { FilterFieldDef } from '@/types/resource';
import { whatsappTemplateService } from '@/services/whatsapp-template-service';
import { qualityLabel } from '@/lib/whatsapp-template';
import { csvEscape } from '@/lib/csv';
import type { TemplateManageItem } from '@/types/whatsapp-template';
import {
  TEMPLATE_STATUS_REGISTRY,
  TEMPLATE_STATUS_OPTIONS,
  TEMPLATE_CATEGORY_OPTIONS,
} from './template-status';
import { TEMPLATE_LANGUAGES } from '@/lib/whatsapp-template';
import { templateEditPath } from './paths';

const stop = (e: React.MouseEvent) => e.stopPropagation();

const FILTER_FIELDS: FilterFieldDef[] = [
  { field: 'name', label: 'Name', type: 'text' },
  { field: 'status', label: 'Status', type: 'enum', options: TEMPLATE_STATUS_OPTIONS },
  { field: 'category', label: 'Category', type: 'enum', options: TEMPLATE_CATEGORY_OPTIONS },
  {
    field: 'language',
    label: 'Language',
    type: 'enum',
    options: TEMPLATE_LANGUAGES.map((l) => ({ label: l, value: l })),
  },
];

/** Translate the Resource shell's FilterGroup → the backend's flat facet params
 * (status/category/language). Only top-level equality leaves are mapped. */
function filtersToExtra(query: ListQuery): Record<string, string> {
  const extra: Record<string, string> = {};
  for (const r of query.filter?.rules ?? []) {
    if ('field' in r && r.operator === 'eq' && typeof r.value === 'string') {
      if (r.field === 'status' || r.field === 'category' || r.field === 'language') {
        extra[r.field] = r.value;
      }
    }
  }
  return extra;
}

export interface UseTemplateListResult {
  config: ResourceListConfig<TemplateManageItem>;
}

export function useTemplateList(
  channelId: string,
  onSubmitTemplate: () => void,
  onEdit: (id: string) => void,
  onViewPayload: (item: TemplateManageItem) => void,
): UseTemplateListResult {
  const actions = useMemo<ResourceAction<TemplateManageItem>[]>(
    () => [
      {
        id: 'edit',
        label: 'Edit',
        icon: Pencil,
        permission: 'wa_templates.manage',
        surfaces: { row: true },
        isVisible: (rows) =>
          rows.length === 1 && !['PENDING', 'DISABLED'].includes(rows[0]?.status),
        run: ([t]) => t && onEdit(t.id),
      },
      {
        id: 'submit',
        label: 'Submit for review',
        icon: Send,
        permission: 'wa_templates.manage',
        surfaces: { row: true, bulk: true },
        // Only drafts can be submitted (any count).
        isVisible: (rows) => rows.length > 0 && rows.every((r) => r.status === 'LOCAL_DRAFT'),
        run: async (rows, rt) => {
          if (!rows.length) return;
          try {
            await Promise.all(rows.map((t) => whatsappTemplateService.submit(channelId, t.id)));
            toast.success(`Submitted ${rows.length} template(s) for review.`);
            rt.reload();
          } catch {
            toast.error('Could not submit. Your drafts are kept — please retry.');
          }
        },
      },
      {
        id: 'view-payload',
        label: 'View payload',
        icon: Code2,
        permission: 'wa_templates.read',
        surfaces: { row: true },
        isVisible: (rows) => rows.length === 1,
        run: ([t]) => t && onViewPayload(t),
      },
      {
        id: 'delete',
        label: 'Delete',
        icon: Trash2,
        tone: 'destructive',
        permission: 'wa_templates.manage',
        surfaces: { row: true, bulk: true },
        isVisible: (rows) => rows.length > 0,
        confirm: {
          title: 'Delete template?',
          description:
            'A local draft is removed here; a synced template is also deleted on Meta. This cannot be undone.',
          confirmLabel: 'Delete',
        },
        run: async (rows, rt) => {
          if (!rows.length) return;
          try {
            await Promise.all(rows.map((t) => whatsappTemplateService.remove(channelId, t.id)));
            toast.success(`Deleted ${rows.length} template(s).`);
            rt.reload();
          } catch {
            toast.error('Could not delete. Please retry.');
          }
        },
      },
    ],
    [channelId, onEdit, onViewPayload],
  );

  const config = useMemo<ResourceListConfig<TemplateManageItem>>(() => {
    const columns: ColumnDef<TemplateManageItem>[] = [
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
        id: 'status',
        accessorFn: (r) => r.status,
        meta: { headerTitle: 'Status' },
        header: ({ column }) => <DataGridColumnHeader title="Status" column={column} />,
        cell: ({ row }) => (
          <div className="flex flex-col items-start gap-0.5">
            <StatusBadge status={row.original.status} registry={TEMPLATE_STATUS_REGISTRY} />
            {row.original.status === 'REJECTED' && row.original.rejectedReason && (
              <span className="text-xs text-destructive">
                Rejection reason: {row.original.rejectedReason}
              </span>
            )}
          </div>
        ),
        size: 170,
        enableSorting: true,
      },
      {
        id: 'name',
        accessorFn: (r) => r.name,
        meta: { headerTitle: 'Name' },
        header: ({ column }) => <DataGridColumnHeader title="Name" column={column} />,
        cell: ({ row }) => (
          <div className="flex items-center gap-2">
            <FileText className="size-4 text-muted-foreground" />
            <ClampedText text={row.original.name} lines={1} className="font-medium" />
          </div>
        ),
        size: 240,
        enableSorting: true,
      },
      {
        id: 'category',
        accessorFn: (r) => r.category,
        meta: { headerTitle: 'Category' },
        header: ({ column }) => <DataGridColumnHeader title="Category" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm capitalize text-muted-foreground">
            {row.original.category ? row.original.category.toLowerCase() : '—'}
          </span>
        ),
        size: 130,
        enableSorting: true,
      },
      {
        id: 'quality',
        accessorFn: (r) => r.quality,
        meta: { headerTitle: 'Quality' },
        header: ({ column }) => <DataGridColumnHeader title="Quality" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">{qualityLabel(row.original.quality)}</span>
        ),
        size: 110,
        enableSorting: false,
      },
      {
        id: 'language',
        accessorFn: (r) => r.language,
        meta: { headerTitle: 'Language' },
        header: ({ column }) => <DataGridColumnHeader title="Language" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">{row.original.language ?? '—'}</span>
        ),
        size: 110,
        enableSorting: false,
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

    return {
      viewKey: `omnichannel.templates.${channelId}`,
      columns,
      getRowId: (t) => t.id,
      rowHref: (t) => templateEditPath(channelId, t.id),
      fetcher: (q) =>
        whatsappTemplateService.listManage(channelId, {
          ...q,
          extra: filtersToExtra(q),
        } as ListQuery),
      exporter: async (q, _cols, ids) => {
        const res = await whatsappTemplateService.listManage(channelId, {
          ...q,
          page: 0,
          pageSize: 200,
          extra: filtersToExtra(q),
        } as ListQuery);
        const picked = ids && ids.length ? res.data.filter((t) => ids.includes(t.id)) : res.data;
        const header = ['Status', 'Name', 'Category', 'Quality', 'Language'].join(',');
        const body = picked
          .map((t) =>
            [t.status, t.name, t.category ?? '', qualityLabel(t.quality), t.language ?? '']
              .map(csvEscape)
              .join(','),
          )
          .join('\n');
        return `${header}\n${body}`;
      },
      exportColumns: [
        { id: 'status', label: 'Status' },
        { id: 'name', label: 'Name' },
        { id: 'category', label: 'Category' },
        { id: 'quality', label: 'Quality' },
        { id: 'language', label: 'Language' },
      ],
      filterFields: FILTER_FIELDS,
      actions,
      searchPlaceholder: 'Search templates…',
      searchHints: ['Name'],
      defaultSort: { id: 'created', desc: true },
      enableStatusViews: false,
      createLabel: 'Submit Template',
      createPermission: 'wa_templates.manage',
      onCreate: onSubmitTemplate,
    };
  }, [channelId, actions, onSubmitTemplate]);

  return { config };
}
