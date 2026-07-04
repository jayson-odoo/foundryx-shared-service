'use client';

import { useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { StatusBadge } from '@/components/platform/status-badge';
import type { ResourceListConfig } from '@/components/platform/resource-list';
import { ClampedText } from '@/components/platform/clamped-text';
import { useDatetime } from '@/hooks/use-datetime';
import { templateEngineService } from '@/services/template-service';
import type { TemplateListItem } from '@/types/templates';
import { TEMPLATES_PATH, templatePath } from './paths';
import { TEMPLATE_TIER_REGISTRY } from './template-tier';
import { useTemplateActions } from './use-template-actions';

export function useTemplatesListConfig(): ResourceListConfig<TemplateListItem> {
  const router = useRouter();
  const actions = useTemplateActions();
  const { formatDateTime } = useDatetime();

  return useMemo<ResourceListConfig<TemplateListItem>>(
    () => ({
      viewKey: 'templates',
      getRowId: (row) => row.id,
      rowHref: (row) => templatePath(row.id),
      fetcher: (query) => templateEngineService.listTemplates(query),
      exporter: (query, columns) => templateEngineService.exportTemplates(query, columns),
      searchPlaceholder: 'Search name, key or subject…',
      searchHints: ['Name', 'Key', 'Subject'],
      defaultSort: { id: 'name', desc: false },
      exportFilename: 'templates',
      createLabel: 'New template',
      createPermission: 'templates.manage',
      onCreate: () => router.push(`${TEMPLATES_PATH}/new`),
      columns: [
        {
          id: 'name',
          accessorFn: (row) => row.name,
          meta: { headerTitle: 'Name' },
          header: ({ column }) => <DataGridColumnHeader title="Name" column={column} />,
          cell: ({ row }) => (
            <div className="flex flex-col">
              <span className="font-medium text-foreground leading-tight">{row.original.name}</span>
              <span className="text-xs text-muted-foreground">{row.original.key}</span>
            </div>
          ),
          size: 240,
          enableSorting: true,
        },
        {
          id: 'subject',
          accessorFn: (row) => row.subject,
          meta: { headerTitle: 'Subject' },
          header: ({ column }) => <DataGridColumnHeader title="Subject" column={column} />,
          cell: ({ row }) => <ClampedText text={row.original.subject} lines={1} />,
          size: 260,
          enableSorting: true,
        },
        {
          id: 'contextLabel',
          accessorFn: (row) => row.contextLabel,
          meta: { headerTitle: 'Context' },
          header: ({ column }) => <DataGridColumnHeader title="Context" column={column} />,
          cell: ({ row }) => (
            <span className="text-sm text-muted-foreground">{row.original.contextLabel}</span>
          ),
          size: 220,
          enableSorting: true,
        },
        {
          id: 'type',
          accessorFn: (row) => row.type,
          meta: { headerTitle: 'Type' },
          header: ({ column }) => <DataGridColumnHeader title="Type" column={column} />,
          cell: ({ row }) => (
            <span className="text-sm capitalize text-muted-foreground">
              {row.original.type === 'badge' ? 'Badge / canvas' : row.original.type}
            </span>
          ),
          size: 130,
          enableSorting: true,
        },
        {
          id: 'tier',
          accessorFn: (row) => row.tier,
          meta: { headerTitle: 'Tier' },
          header: ({ column }) => <DataGridColumnHeader title="Tier" column={column} />,
          cell: ({ row }) => (
            <StatusBadge status={row.original.tier} registry={TEMPLATE_TIER_REGISTRY} size="sm" />
          ),
          size: 120,
          enableSorting: true,
        },
        {
          id: 'updatedAt',
          accessorFn: (row) => row.updatedAt,
          meta: { headerTitle: 'Updated' },
          header: ({ column }) => <DataGridColumnHeader title="Updated" column={column} />,
          cell: ({ row }) => (
            <span className="text-sm text-muted-foreground">
              {formatDateTime(row.original.updatedAt)}
            </span>
          ),
          size: 160,
          enableSorting: true,
        },
      ],
      filterFields: [
        { field: 'name', label: 'Name', type: 'text' },
        { field: 'key', label: 'Key', type: 'text' },
        { field: 'subject', label: 'Subject', type: 'text' },
        {
          field: 'type',
          label: 'Type',
          type: 'enum',
          options: [
            { label: 'Email', value: 'email' },
            { label: 'Document', value: 'document' },
            { label: 'Badge / canvas', value: 'badge' },
          ],
        },
        {
          field: 'tier',
          label: 'Tier',
          type: 'enum',
          options: [
            { label: 'Default', value: 'default' },
            { label: 'Customized', value: 'customized' },
          ],
        },
      ],
      exportColumns: [
        { id: 'name', label: 'Name' },
        { id: 'key', label: 'Key' },
        { id: 'subject', label: 'Subject' },
        { id: 'contextLabel', label: 'Context' },
        { id: 'tier', label: 'Tier' },
        { id: 'updatedAt', label: 'Updated' },
      ],
      actions,
    }),
    [actions, router, formatDateTime],
  );
}
