'use client';

import { useMemo } from 'react';
import { CheckCheck, CircleStop, RotateCcw } from 'lucide-react';
import { toast } from '@/lib/toast';
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
        // Grace-window deferred action (sprint-4/23, T5 fix round 1, item
        // 15) - no confirm, no `run` (the registered `jobs.abort` handler
        // commits it server-side).
        deferred: { actionKey: 'jobs.abort', entityType: 'background_job' },
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
        // Grace-window deferred action - no confirm, no `run` (the
        // registered `jobs.complete` handler commits it server-side).
        deferred: { actionKey: 'jobs.complete', entityType: 'background_job' },
      },
    ],
    [],
  );
}
