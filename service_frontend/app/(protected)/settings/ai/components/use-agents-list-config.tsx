'use client';

import { useMemo } from 'react';
import { useRouter } from 'next/navigation';
import type { ColumnDef } from '@tanstack/react-table';
import { TriangleAlert } from 'lucide-react';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import {
  DataGridTableRowSelect,
  DataGridTableRowSelectAll,
} from '@/components/ui/data-grid-table';
import { Badge } from '@/components/ui/badge';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import type { ResourceListConfig } from '@/components/platform/resource-list';
import { ClampedText } from '@/components/platform/clamped-text';
import { OverflowPills } from '@/components/platform/overflow-pills';
import { useDatetime } from '@/hooks/use-datetime';
import { aiService } from '@/services/ai-service';
import type { AiAgent } from '@/types/ai';
import { AI_AGENTS_PATH, agentPath } from './paths';
import { useAgentActions } from './use-agent-actions';

const stop = (e: React.MouseEvent) => e.stopPropagation();

export function useAgentsListConfig(): ResourceListConfig<AiAgent> {
  const router = useRouter();
  const actions = useAgentActions();
  const { formatDateTime } = useDatetime();

  return useMemo<ResourceListConfig<AiAgent>>(() => {
    const columns: ColumnDef<AiAgent>[] = [
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
        size: 240,
        enableSorting: true,
      },
      {
        id: 'connectionName',
        accessorFn: (row) => row.connectionName,
        meta: { headerTitle: 'Connection' },
        header: ({ column }) => <DataGridColumnHeader title="Connection" column={column} />,
        cell: ({ row }) => {
          const { connectionName, warning } = row.original;
          // The missing-prerequisite warning rides the list, not just the form -
          // a broken agent is visible BEFORE anyone tries to run it (AC-BI-06).
          if (warning) {
            return (
              <Tooltip>
                <TooltipTrigger asChild>
                  <span className="flex items-center gap-1.5 text-sm text-warning">
                    <TriangleAlert className="size-3.5 shrink-0" />
                    {connectionName ?? 'Not configured'}
                  </span>
                </TooltipTrigger>
                <TooltipContent>{warning}</TooltipContent>
              </Tooltip>
            );
          }
          return <span className="text-sm text-muted-foreground">{connectionName}</span>;
        },
        size: 190,
        enableSorting: false,
      },
      {
        id: 'model',
        accessorFn: (row) => row.model,
        meta: { headerTitle: 'Model' },
        header: ({ column }) => <DataGridColumnHeader title="Model" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">{row.original.model || '-'}</span>
        ),
        size: 180,
        enableSorting: true,
      },
      {
        id: 'skills',
        accessorFn: (row) => row.skills.map((s) => s.name).join(', '),
        meta: { headerTitle: 'Skills' },
        header: ({ column }) => <DataGridColumnHeader title="Skills" column={column} />,
        cell: ({ row }) =>
          row.original.skills.length ? (
            <OverflowPills
              items={row.original.skills}
              keyFor={(s) => s.id}
              renderPill={(s) => (
                <Badge variant="secondary" appearance="light" size="sm">
                  {s.name}
                </Badge>
              )}
            />
          ) : (
            <span className="text-sm text-muted-foreground">-</span>
          ),
        size: 200,
        enableSorting: false,
      },
      {
        id: 'isEnabled',
        accessorFn: (row) => row.isEnabled,
        meta: { headerTitle: 'Status' },
        header: ({ column }) => <DataGridColumnHeader title="Status" column={column} />,
        cell: ({ row }) => (
          <div className="flex items-start">
            <Badge
              variant={row.original.isEnabled ? 'success' : 'secondary'}
              appearance="light"
              size="sm"
            >
              {row.original.isEnabled ? 'Enabled' : 'Disabled'}
            </Badge>
          </div>
        ),
        size: 110,
        enableSorting: true,
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
      viewKey: 'ai.agents',
      // No soft-trash on agents - offering a "Trashed" view that can never
      // hold anything is a foolproof-UI violation (only offer valid options).
      enableStatusViews: false,
      getRowId: (row) => row.id,
      rowHref: (row) => agentPath(row.id),
      fetcher: (query) => aiService.listAgents(query),
      exporter: (query, exportColumns) => aiService.exportAgents(query, exportColumns),
      searchPlaceholder: 'Search agents…',
      searchHints: ['Name', 'Description', 'Model'],
      defaultSort: { id: 'name', desc: false },
      exportFilename: 'ai-agents',
      createLabel: 'New agent',
      createPermission: 'ai_agents.manage',
      onCreate: () => router.push(`${AI_AGENTS_PATH}/new`),
      columns,
      filterFields: [
        { field: 'name', label: 'Name', type: 'text' },
        { field: 'model', label: 'Model', type: 'text' },
        {
          field: 'isEnabled',
          label: 'Status',
          type: 'enum',
          options: [
            { label: 'Enabled', value: 'true' },
            { label: 'Disabled', value: 'false' },
          ],
        },
      ],
      exportColumns: [
        { id: 'name', label: 'Name' },
        { id: 'connectionName', label: 'Connection' },
        { id: 'model', label: 'Model' },
        { id: 'temperature', label: 'Temperature' },
        { id: 'isEnabled', label: 'Enabled' },
      ],
      actions,
    };
  }, [actions, router, formatDateTime]);
}
