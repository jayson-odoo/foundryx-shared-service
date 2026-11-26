'use client';

import { useMemo } from 'react';
import type { ColumnDef } from '@tanstack/react-table';
import { Play } from 'lucide-react';
import { toast } from '@/lib/toast';
import { DataGridColumnHeader } from '@/components/ui/data-grid-column-header';
import { ClampedText } from '@/components/platform/clamped-text';
import { ActionMenu } from '@/components/platform/resource-actions/action-menu';
import { embeddedListConfig } from '@/components/platform/resource-list/embedded-list-config';
import type { ResourceAction, ResourceListConfig } from '@/components/platform/resource-list';
import { hubConnectorErrorMessage } from '@/hooks/use-hub-connector';
import { useDatetime } from '@/hooks/use-datetime';
import { applyClientQuery, type ClientListSpec } from '@/lib/client-list-query';
import { hubConnectorService } from '@/services/hub-connector-service';
import type { ScheduledTask } from '@/types/hub-connector';
import type { ListQuery, ListResult } from '@/types/resource';
import { HUB_MANAGE } from './hub-meta';

const stop = (e: React.MouseEvent) => e.stopPropagation();

const spec: ClientListSpec<ScheduledTask> = {
  searchText: (t) => [t.name, t.schedule],
  value: (t, field) => {
    switch (field) {
      case 'name':
        return t.name.toLowerCase();
      case 'schedule':
        return t.schedule.toLowerCase();
      case 'lastRunAt':
        return t.lastRunAt;
      case 'lastError':
        return t.lastError;
      default:
        return null;
    }
  },
};

/** Run one task now: toast the outcome, then reload the list. */
export const RUN_TASK_ACTION: ResourceAction<ScheduledTask> = {
  id: 'run-now',
  label: 'Run now',
  icon: Play,
  permission: HUB_MANAGE,
  surfaces: { row: true },
  isVisible: (rows) => rows.length === 1,
  run: async (rows, runtime) => {
    try {
      const list = await hubConnectorService.runScheduledTask(rows[0].key);
      const after = list.find((t) => t.key === rows[0].key);
      if (after?.lastError) toast.error(after.lastError);
      else toast.success(`${rows[0].name} ran.`);
    } catch (err) {
      toast.error(hubConnectorErrorMessage(err, 'Could not run the task. Please try again.'));
    }
    runtime.reload();
  },
};

/** Scheduled tasks inside the hubs gear dialog: a handful, loaded whole and paged client-side. */
export function useScheduledTasksListConfig(): ResourceListConfig<ScheduledTask> {
  const { formatDmyDateTime } = useDatetime();

  return useMemo<ResourceListConfig<ScheduledTask>>(() => {
    const actions = [RUN_TASK_ACTION];
    const col = (
      id: string,
      title: string,
      size: number,
      cell: ColumnDef<ScheduledTask>['cell'],
    ): ColumnDef<ScheduledTask> => ({
      id,
      accessorFn: (r) => spec.value(r, id) as string | null,
      meta: { headerTitle: title },
      header: ({ column }) => <DataGridColumnHeader title={title} column={column} />,
      cell,
      size,
      enableSorting: true,
    });
    const columns: ColumnDef<ScheduledTask>[] = [
      col('name', 'Task', 180, ({ row }) => <ClampedText text={row.original.name} lines={1} className="font-medium" />),
      col('schedule', 'Schedule', 160, ({ row }) => (
        <ClampedText text={row.original.schedule} lines={1} className="text-sm" />
      )),
      col('lastRunAt', 'Last run', 170, ({ row }) => (
        <span className="text-sm text-muted-foreground">
          {row.original.lastRunAt ? formatDmyDateTime(row.original.lastRunAt) : '-'}
        </span>
      )),
      col('lastError', 'Last error', 240, ({ row }) => (
        <ClampedText text={row.original.lastError || '-'} lines={1} className="text-sm" />
      )),
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
                runtime={{
                  ctx: meta?.resourceCtx,
                  index: (meta?.pageStartIndex ?? 0) + row.index,
                  reload: meta?.reload ?? (() => {}),
                }}
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
    const fetcher = async (query: ListQuery): Promise<ListResult<ScheduledTask>> =>
      applyClientQuery(await hubConnectorService.listScheduledTasks(), query, spec);
    return {
      enableStatusViews: false,
      ...embeddedListConfig<ScheduledTask>({
        viewKey: 'hub-connector.scheduled-tasks',
        columns,
        fetcher,
        getRowId: (t) => t.key,
        rowHref: () => '#',
        searchPlaceholder: 'Search tasks…',
        defaultSort: { id: 'name', desc: false },
        actions,
      }),
    };
  }, [formatDmyDateTime]);
}
