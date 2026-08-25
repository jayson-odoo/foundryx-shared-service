'use client';

import { useMemo } from 'react';
import { CheckCheck, CircleStop, RotateCcw } from 'lucide-react';
import { toast } from 'sonner';
import type { ResourceAction } from '@/components/platform/resource-list';
import { jobsService } from '@/services/jobs-service';
import type { Job } from '@/types/jobs';

const MIGRATE_PERM = 'integrations.migrate_storage';

/**
 * Background-job action registry (sprint-4/10) - Abort / Retry / Complete,
 * state-aware via `isVisible`, gated by `integrations.migrate_storage` (the
 * job-control ops are storage-migration controls). Surfaced in the `/jobs` row
 * "…" menu and the `/jobs/[id]` detail "…" menu.
 */
export function useJobActions(): ResourceAction<Job>[] {
  return useMemo<ResourceAction<Job>[]>(
    () => [
      {
        id: 'abort',
        label: 'Abort',
        icon: CircleStop,
        tone: 'destructive',
        permission: MIGRATE_PERM,
        surfaces: { row: true, form: true },
        isVisible: (rows) =>
          rows.length === 1 && ['pending', 'running'].includes(rows[0].status),
        confirm: {
          title: 'Abort this migration?',
          description:
            'Copying stops and no references are switched over. New uploads keep landing on the new bucket; existing assets keep serving. You can retry later.',
          confirmLabel: 'Abort',
        },
        run: async ([job], rt) => {
          await jobsService.abortJob(job.id);
          toast.success('Migration aborted.');
          rt.reload();
        },
      },
      {
        id: 'retry',
        label: 'Retry',
        icon: RotateCcw,
        permission: MIGRATE_PERM,
        surfaces: { row: true, form: true },
        isVisible: (rows) =>
          rows.length === 1 && ['failed', 'needs_review'].includes(rows[0].status),
        run: async ([job], rt) => {
          await jobsService.retryJob(job.id);
          toast.success('Migration retrying.');
          rt.reload();
        },
      },
      {
        id: 'complete',
        label: 'Complete anyway',
        icon: CheckCheck,
        permission: MIGRATE_PERM,
        surfaces: { row: true, form: true },
        isVisible: (rows) => rows.length === 1 && rows[0].status === 'needs_review',
        confirm: {
          title: 'Complete with failures?',
          description:
            'Successfully-copied assets are switched to the new bucket; failed ones keep serving from the old bucket. This cannot be undone.',
          confirmLabel: 'Complete',
        },
        run: async ([job], rt) => {
          await jobsService.completeJob(job.id);
          toast.success('Migration completed.');
          rt.reload();
        },
      },
    ],
    [],
  );
}
