'use client';

import { useMemo } from 'react';
import { CircleStop } from 'lucide-react';
import { toast } from '@/lib/toast';
import { ApiError } from '@/lib/api-client';
import type { ResourceAction } from '@/components/platform/resource-list';
import { respondioMigrationService } from '@/services/respondio-migration-service';
import { MIGRATION_JOB_IN_FLIGHT, type MigrationJob } from '@/types/respondio-migration';

const MIGRATION_MANAGE = 'omnichannel_migration.manage';

/**
 * Migration job action registry (plan 33, AC-MIG-08/57) - Abort only,
 * state-aware, gated by `omnichannel_migration.manage`.
 *
 * S6 decision (the S2 handoff flagged this explicitly): Abort calls the
 * DEDICATED `POST /omnichannel/migration/jobs/{id}/cancel` route directly
 * via `respondioMigrationService.cancelJob`, NOT the S0 mock's `deferred:
 * {actionKey:'jobs.abort'}` wiring - that backend handler
 * (`app/deferred_actions/handlers.py _jobs_abort`) hardcodes
 * `StorageMigrationService(db).abort(...)`, a different job type entirely,
 * and the generic core `/jobs/{id}/{abort,retry,complete}` routes
 * (`app/api/v1/jobs.py`) are ALL hard-scoped the same way - so `Retry` and
 * `Complete anyway` are DROPPED from this registry rather than shipped
 * pointed at the wrong backend (no S1-S5 route exists for either on this job
 * type; `needs_review` is likewise never actually reached by the real
 * handler - imported only for the `migration_in_progress` guard's own
 * non-terminal-status set). A plain immediate `run` (no confirm dialog, no
 * grace window) mirrors this same file's OWN prior `retry`/`complete`
 * actions and the hard-fail rule against NEW confirm dialogs outside the
 * named carve-outs - aborting a migration is not one of them, and the
 * dedicated route is a direct commit with no undo, so a grace-window
 * `DeferredActionButton` would falsely promise one.
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
        run: async ([job], rt) => {
          try {
            await respondioMigrationService.cancelJob(job.id);
            toast.success('Migration aborted.');
            rt.reload();
          } catch (error) {
            const reason = error instanceof ApiError ? (error.detail as { reason?: string } | null)?.reason : null;
            toast.error(
              reason === 'not_in_progress'
                ? 'This migration already finished.'
                : 'Could not abort the migration. Please try again.',
            );
          }
        },
      },
    ],
    [],
  );
}
