'use client';

import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Flag } from 'lucide-react';
import { toast } from 'sonner';
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
import type { AiTrace } from '@/types/ai';
import { tracePath } from './paths';

const stop = (e: React.MouseEvent) => e.stopPropagation();

function useTraceActions(): ResourceAction<AiTrace>[] {
  return useMemo<ResourceAction<AiTrace>[]>(
    () => [
      {
        id: 'flag',
        // Derived label - the same action reads as its effect on the row.
        label: (rows) => (rows.every((t) => t.flagged) ? 'Remove flag' : 'Flag for review'),
        icon: Flag,
        surfaces: { row: true, bulk: true, form: true },
        permission: 'ai_traces.read',
        run: async (rows, runtime) => {
          const flagged = !rows.every((t) => t.flagged);
          for (const trace of rows) await aiService.flagTrace(trace.id, flagged);
          // Flagging is what keeps a trace past the short `ok` retention window.
          toast.success(flagged ? 'Flagged for review.' : 'Flag removed.');
          runtime.reload();
        },
      },
    ],
    [],
  );
}

export function useTracesListConfig(): ResourceListConfig<AiTrace> {
  const actions = useTraceActions();
  const { formatDateTime } = useDatetime();

  return useMemo<ResourceListConfig<AiTrace>>(() => {
    const columns: ColumnDef<AiTrace>[] = [
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
        id: 'created',
        accessorFn: (row) => row.createdAt,
        meta: { headerTitle: 'When' },
        header: ({ column }) => <DataGridColumnHeader title="When" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">
            {row.original.createdAt ? formatDateTime(row.original.createdAt) : '-'}
          </span>
        ),
        size: 170,
        enableSorting: true,
      },
      {
        id: 'agentName',
        accessorFn: (row) => row.agentName,
        meta: { headerTitle: 'Agent' },
        header: ({ column }) => <DataGridColumnHeader title="Agent" column={column} />,
        cell: ({ row }) => (
          <div className="flex flex-col">
            <span className="font-medium leading-tight text-foreground">
              {row.original.agentName || '-'}
            </span>
            {row.original.skillKey && (
              <span className="font-mono text-xs text-muted-foreground">
                {row.original.skillKey}
                {row.original.promptVersion ? ` v${row.original.promptVersion}` : ''}
              </span>
            )}
          </div>
        ),
        size: 200,
        enableSorting: true,
      },
      {
        id: 'model',
        accessorFn: (row) => row.model,
        meta: { headerTitle: 'Model' },
        header: ({ column }) => <DataGridColumnHeader title="Model" column={column} />,
        cell: ({ row }) => (
          <div className="flex flex-col">
            <span className="text-sm text-foreground">{row.original.model || '-'}</span>
            <span className="text-xs text-muted-foreground">{row.original.provider}</span>
          </div>
        ),
        size: 170,
        enableSorting: true,
      },
      {
        id: 'status',
        accessorFn: (row) => row.status,
        meta: { headerTitle: 'Status' },
        header: ({ column }) => <DataGridColumnHeader title="Status" column={column} />,
        cell: ({ row }) => (
          <div className="flex flex-wrap items-start gap-1.5">
            <Badge
              variant={row.original.status === 'ok' ? 'success' : 'destructive'}
              appearance="light"
              size="sm"
            >
              {row.original.status === 'ok' ? 'OK' : 'Error'}
            </Badge>
            {row.original.flagged && (
              <Badge variant="warning" appearance="light" size="sm">
                Flagged
              </Badge>
            )}
          </div>
        ),
        size: 140,
        enableSorting: true,
      },
      {
        id: 'tokens',
        accessorFn: (row) => row.tokensIn + row.tokensOut,
        meta: { headerTitle: 'Tokens' },
        header: ({ column }) => <DataGridColumnHeader title="Tokens" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">
            {row.original.tokensIn} in / {row.original.tokensOut} out
          </span>
        ),
        size: 140,
        enableSorting: false,
      },
      {
        id: 'latencyMs',
        accessorFn: (row) => row.latencyMs,
        meta: { headerTitle: 'Latency' },
        header: ({ column }) => <DataGridColumnHeader title="Latency" column={column} />,
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">{row.original.latencyMs} ms</span>
        ),
        size: 110,
        enableSorting: true,
      },
      {
        id: 'error',
        accessorFn: (row) => row.error,
        meta: { headerTitle: 'Error' },
        header: ({ column }) => <DataGridColumnHeader title="Error" column={column} />,
        cell: ({ row }) =>
          row.original.error ? (
            <ClampedText text={row.original.error} lines={2} className="text-xs text-destructive" />
          ) : (
            <span className="text-xs text-muted-foreground">-</span>
          ),
        size: 220,
        enableSorting: false,
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
      viewKey: 'ai.traces',
      // Traces age out via the retention sweep - there is no trashed view.
      enableStatusViews: false,
      getRowId: (row) => row.id,
      rowHref: (row) => tracePath(row.id),
      fetcher: (query) => aiService.listTraces(query),
      exporter: (query, exportColumns) => aiService.exportTraces(query, exportColumns),
      exportFilename: 'ai-traces',
      // Metadata only - raw prompts/completions stay on the trace detail rather
      // than flowing into a spreadsheet.
      exportColumns: [
        { id: 'created', label: 'When' },
        { id: 'agentName', label: 'Agent' },
        { id: 'provider', label: 'Provider' },
        { id: 'model', label: 'Model' },
        { id: 'status', label: 'Status' },
        { id: 'tokensIn', label: 'Tokens in' },
        { id: 'tokensOut', label: 'Tokens out' },
        { id: 'latencyMs', label: 'Latency (ms)' },
        { id: 'flagged', label: 'Flagged' },
      ],
      searchPlaceholder: 'Search traces…',
      searchHints: ['Agent', 'Model', 'Provider', 'Error'],
      // Newest first - the useful order when debugging.
      defaultSort: { id: 'created', desc: true },
      columns,
      filterFields: [
        { field: 'agentName', label: 'Agent', type: 'text' },
        { field: 'model', label: 'Model', type: 'text' },
        {
          field: 'status',
          label: 'Status',
          type: 'enum',
          options: [
            { label: 'OK', value: 'ok' },
            { label: 'Error', value: 'error' },
          ],
        },
        { field: 'flagged', label: 'Flagged', type: 'bool' },
      ],
      actions,
    };
  }, [actions, formatDateTime]);
}
