'use client';

import { useMemo } from 'react';
import { CheckCheck, CircleStop, RotateCcw } from 'lucide-react';
import { toast } from '@/lib/toast';
import type { ResourceAction } from '@/components/platform/resource-list';
import { jobsService } from '@/services/jobs-service';
import { MIGRATION_JOB_IN_FLIGHT, type MigrationJob } from '@/types/respondio-migration';

const MIGRATION_MANAGE = 'omnichannel_migration.manage';

/**
 * Migration job action registry (plan 33 S0, AC-MIG-08) - Abort / Retry /
 * Complete, state-aware, gated by `omnichannel_migration.manage`. The job's
 * `id` IS the generic `background_jobs` id (plan §2.1 "reused, unchanged
 * POST /jobs/{jobId}/abort, GET /jobs/{jobId}") so this reuses the CORE
 * `jobsService`/`jobs.abort` deferred handler wholesale (`use-job-actions.tsx`
 * precedent) rather than standing up a parallel abort path.
 */
export function useMigrationActions(): ResourceAction<MigrationJob>[] {
  return useMemo<ResourceAction<MigrationJob>[]>(
    () => [
      {
        id: 'abort',
        label: 'Abort',
        icon: CircleStop,
        tone: 'destructive',
        permission: MIGRATION_MANAGE,
        surfaces: { row: true, form: true },
        isVisible: (rows) => rows.length === 1 && MIGRATION_JOB_IN_FLIGHT.has(rows[0].status),
        // Grace-window deferred action (the `jobs.abort` registry precedent,
        // sprint-4/23 T5) - no confirm dialog, no `run`.
        deferred: { actionKey: 'jobs.abort', entityType: 'background_job' },
      },
      {
        id: 'retry',
        label: 'Retry',
        icon: RotateCcw,
        permission: MIGRATION_MANAGE,
        surfaces: { row: true, form: true },
        isVisible: (rows) => rows.length === 1 && ['failed', 'needs_review'].includes(rows[0].status),
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
        permission: MIGRATION_MANAGE,
        surfaces: { row: true, form: true },
        isVisible: (rows) => rows.length === 1 && rows[0].status === 'needs_review',
        deferred: { actionKey: 'jobs.complete', entityType: 'background_job' },
      },
    ],
    [],
  );
}
