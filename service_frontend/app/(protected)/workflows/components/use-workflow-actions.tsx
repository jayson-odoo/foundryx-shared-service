'use client';

import { useMemo } from 'react';
import { useRouter } from 'next/navigation';
import {
  Archive,
  ArchiveRestore,
  CloudOff,
  CloudUpload,
  Copy,
  Pencil,
  Trash2,
} from 'lucide-react';
import { toast } from 'sonner';
import type { WorkflowListItem } from '@/types/workflows';
import { workflowPublishIssue } from '@/lib/workflow-validation';
import { useCan } from '@/hooks/use-can';
import { workflowMetadataService } from '@/services/workflow-metadata-service';
import { workflowService } from '@/services/workflow-service';
import type { ResourceAction } from '@/components/platform/resource-list';
import { workflowPath } from './paths';

const publishable = (w: WorkflowListItem) =>
  w.currentVersionNumber == null || w.hasUnpublishedChanges;

/** ONE action registry - row `…`, bulk dropdown and form `…` share it.
 * Visibility branches on the Active vs Archived view (via `isTrashed`). */
export function useWorkflowActions(): ResourceAction<WorkflowListItem>[] {
  const router = useRouter();
  const { can } = useCan();
  const canCode = can('workflows.code');

  return useMemo<ResourceAction<WorkflowListItem>[]>(
    () => [
      {
        id: 'edit',
        label: 'Edit',
        icon: Pencil,
        surfaces: { row: true },
        permission: 'workflows.manage',
        isVisible: (rows) => rows.every((w) => !w.isTrashed),
        run: ([w]) => router.push(`${workflowPath(w.id)}?edit=1`),
      },
      {
        id: 'publish',
        label: 'Publish',
        icon: CloudUpload,
        surfaces: { row: true, bulk: true },
        permission: 'workflows.manage',
        // Only when every selected row has something to publish.
        isVisible: (rows) =>
          rows.length > 0 && rows.every((w) => !w.isTrashed && publishable(w)),
        run: async (rows, runtime) => {
          try {
            const [fullWorkflows, metadata] = await Promise.all([
              Promise.all(rows.map((row) => workflowService.get(row.id))),
              workflowMetadataService.getMetadata(),
            ]);
            for (const workflow of fullWorkflows) {
              if (!workflow) throw new Error('Workflow not found.');
              const issue = workflowPublishIssue(workflow, metadata, canCode);
              if (issue) throw new Error(issue);
            }
            for (const w of rows) await workflowService.publish(w.id);
            toast.success(
              `Published ${rows.length} workflow${rows.length === 1 ? '' : 's'}.`,
            );
            runtime.reload();
          } catch (error) {
            toast.error(
              error instanceof Error ? error.message : 'Publish failed.',
            );
          }
        },
      },
      {
        id: 'unpublish',
        label: 'Unpublish',
        icon: CloudOff,
        surfaces: { row: true, bulk: true },
        permission: 'workflows.manage',
        isVisible: (rows) =>
          rows.length > 0 &&
          rows.every((w) => !w.isTrashed && w.currentVersionNumber != null),
        run: async (rows, runtime) => {
          for (const w of rows) await workflowService.unpublish(w.id);
          toast.success(
            `Unpublished ${rows.length} workflow${rows.length === 1 ? '' : 's'}.`,
          );
          runtime.reload();
        },
      },
      {
        id: 'duplicate',
        label: 'Duplicate',
        icon: Copy,
        surfaces: { row: true, form: true },
        permission: 'workflows.manage',
        isVisible: (rows) => rows.every((w) => !w.isTrashed),
        run: async ([w], runtime) => {
          const copy = await workflowService.duplicate(w.id);
          toast.success(`Duplicated as "${copy.name}".`);
          runtime.reload();
        },
      },
      {
        id: 'archive',
        label: 'Archive',
        icon: Archive,
        surfaces: { row: true, bulk: true, form: true },
        permission: 'workflows.manage',
        isVisible: (rows) => rows.length > 0 && rows.every((w) => !w.isTrashed),
        run: async (rows, runtime) => {
          for (const w of rows) await workflowService.archive(w.id);
          toast.success(
            `Archived ${rows.length} workflow${rows.length === 1 ? '' : 's'}.`,
          );
          runtime.reload();
        },
      },
      {
        id: 'restore',
        label: 'Restore',
        icon: ArchiveRestore,
        surfaces: { row: true, bulk: true },
        permission: 'workflows.manage',
        isVisible: (rows) => rows.length > 0 && rows.every((w) => w.isTrashed),
        run: async (rows, runtime) => {
          for (const w of rows) await workflowService.restore(w.id);
          toast.success(
            `Restored ${rows.length} workflow${rows.length === 1 ? '' : 's'}.`,
          );
          runtime.reload();
        },
      },
      {
        id: 'delete',
        label: 'Delete permanently',
        icon: Trash2,
        tone: 'destructive',
        surfaces: { row: true, bulk: true },
        permission: 'workflows.manage',
        // Hard delete only from the Archived view (two-step safety).
        isVisible: (rows) => rows.length > 0 && rows.every((w) => w.isTrashed),
        // Grace-window deferred action (sprint-4/23, T5, D2) - no confirm,
        // no `run` (the registered `workflows.delete` handler commits it).
        deferred: { actionKey: 'workflows.delete', entityType: 'workflow' },
      },
    ],
    [canCode, router],
  );
}
