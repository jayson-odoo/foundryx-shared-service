'use client';

import { useMemo } from 'react';
import { useRouter } from 'next/navigation';
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
import { ClampedText } from '@/components/platform/clamped-text';
import { useDatetime } from '@/hooks/use-datetime';
import { aiService } from '@/services/ai-service';
import type { AiSkill } from '@/types/ai';
import { AI_SKILLS_PATH, skillPath } from './paths';

const stop = (e: React.MouseEvent) => e.stopPropagation();

export function useSkillActions(): ResourceAction<AiSkill>[] {
  const router = useRouter();

  return useMemo<ResourceAction<AiSkill>[]>(
    () => [
      {
        id: 'edit',
        label: 'Edit',
        icon: Pencil,
        surfaces: { row: true },
        permission: 'ai_agents.manage',
        run: ([skill]) => router.push(`${skillPath(skill.id)}?edit=1`),
      },
      {
        id: 'delete',
        label: 'Delete',
        icon: Trash2,
        tone: 'destructive',
        surfaces: { row: true, bulk: true, form: true },
        permission: 'ai_agents.manage',
        // A shared platform default is not the tenant's to delete; the backend
        // 409s regardless, but hiding it keeps the menu honest (foolproof-UI).
        isVisible: (rows) => rows.length > 0 && rows.every((s) => !s.isPlatform && !s.isSystem),
        // Grace-window deferred action (sprint-4/23, T5, D2) - no confirm,
        // no `run` (the registered `ai_skills.delete` handler commits it).
        deferred: { actionKey: 'ai_skills.delete', entityType: 'ai_skill' },
      },
    ],
    [router],
  );
}

export function useSkillsListConfig(): ResourceListConfig<AiSkill> {
  const router = useRouter();
  const actions = useSkillActions();
  const { formatDateTime } = useDatetime();

  return useMemo<ResourceListConfig<AiSkill>>(() => {
    const columns: ColumnDef<AiSkill>[] = [
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
          <div className="flex flex-col">
            <span className="font-medium leading-tight text-foreground">{row.original.name}</span>
            <ClampedText
              text={row.original.description}
              lines={1}
              className="text-xs text-muted-foreground"
            />
          </div>
        ),
        size: 260,
        enableSorting: true,
      },
      {
        id: 'key',
        accessorFn: (row) => row.key,
        meta: { headerTitle: 'Key' },
        header: ({ column }) => <DataGridColumnHeader title="Key" column={column} />,
        cell: ({ row }) => (
          <span className="font-mono text-xs text-muted-foreground">{row.original.key}</span>
        ),
        size: 180,
        enableSorting: true,
      },
      {
        id: 'activeVersionNumber',
        accessorFn: (row) => row.activeVersionNumber,
        meta: { headerTitle: 'Active version' },
        header: ({ column }) => <DataGridColumnHeader title="Active version" column={column} />,
        cell: ({ row }) => (
          <div className="flex items-center gap-1.5">
            <span className="text-sm text-foreground">
              {row.original.activeVersionNumber ? `v${row.original.activeVersionNumber}` : '-'}
            </span>
            <span className="text-xs text-muted-foreground">
              of {row.original.versionCount}
            </span>
          </div>
        ),
        size: 150,
        enableSorting: false,
      },
      {
        id: 'tier',
        accessorFn: (row) => row.isPlatform,
        meta: { headerTitle: 'Source' },
        header: ({ column }) => <DataGridColumnHeader title="Source" column={column} />,
        cell: ({ row }) => (
          <div className="flex items-start">
            <Badge
              variant={row.original.isPlatform ? 'secondary' : 'primary'}
              appearance="light"
              size="sm"
            >
              {row.original.isPlatform ? 'Provided' : 'Custom'}
            </Badge>
          </div>
        ),
        size: 110,
        enableSorting: false,
      },
      {
        id: 'updatedAt',
        accessorFn: (row) => row.updatedAt,
        meta: { headerTitle: 'Updated' },
        header: ({ column }) => <DataGridColumnHeader title="Updated" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">
            {row.original.updatedAt ? formatDateTime(row.original.updatedAt) : '-'}
          </span>
        ),
        size: 150,
        enableSorting: true,
      },
      {
        id: 'actions',
        meta: { reorderable: false },
        header: () => null,
        cell: ({ row, table }) => {
          const meta = table.options.meta;
          return (
            <div onClick={stop} className="flex justify-end">
              <ActionMenu
                actions={actions}
                rows={[row.original]}
                runtime={{ reload: meta?.reload ?? (() => {}) }}
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
      viewKey: 'ai.skills',
      // Skills are deleted outright, never soft-trashed.
      enableStatusViews: false,
      getRowId: (row) => row.id,
      rowHref: (row) => skillPath(row.id),
      fetcher: (query) => aiService.listSkills(query),
      exporter: (query, exportColumns) => aiService.exportSkills(query, exportColumns),
      searchPlaceholder: 'Search skills…',
      searchHints: ['Name', 'Key', 'Description'],
      defaultSort: { id: 'name', desc: false },
      exportFilename: 'ai-skills',
      createLabel: 'New skill',
      createPermission: 'ai_agents.manage',
      onCreate: () => router.push(`${AI_SKILLS_PATH}/new`),
      columns,
      filterFields: [
        { field: 'name', label: 'Name', type: 'text' },
        { field: 'key', label: 'Key', type: 'text' },
      ],
      exportColumns: [
        { id: 'key', label: 'Key' },
        { id: 'name', label: 'Name' },
        { id: 'activeVersionNumber', label: 'Active version' },
        { id: 'versionCount', label: 'Versions' },
      ],
      actions,
    };
  }, [actions, router, formatDateTime]);
}
