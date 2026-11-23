/**
 * Background-work words for migration jobs under the Foundryx UIUX switch
 * (slice W2-WS, gap audit "Work that runs in the background"): progress as
 * "820 of 1,240" from the server's own counts, never a guess. While the
 * total is still unknown (the backend learns it only at the end) the count
 * stands alone.
 */
import type { MigrationJob } from '@/types/respondio-migration';
import { MIGRATION_JOB_IN_FLIGHT } from '@/types/respondio-migration';

const n = (v: number) => v.toLocaleString('en-US');

/** "820 of 1,240" or "820 so far". */
export function fxMigrationCount(
  job: Pick<MigrationJob, 'progressDone' | 'progressTotal' | 'status'>,
): string {
  if (job.progressTotal > 0)
    return `${n(job.progressDone)} of ${n(job.progressTotal)}`;
  return MIGRATION_JOB_IN_FLIGHT.has(job.status)
    ? `${n(job.progressDone)} so far`
    : n(job.progressDone);
}

/** The progress card's headline for the job's state. */
export function fxMigrationHeadline(
  job: Pick<MigrationJob, 'status' | 'progressFailed'>,
): string {
  switch (job.status) {
    case 'pending':
      return 'Waiting to start in the background';
    case 'running':
      return 'Running in the background';
    case 'done':
      return job.progressFailed > 0 ? 'Done with errors' : 'Done';
    case 'needs_review':
      return 'Done, needs review';
    case 'failed':
      return 'Failed';
    case 'aborted':
      return 'Stopped';
    default:
      return '';
  }
}

/** "820 of 1,240 processed, 2 failed". */
export function fxMigrationLine(
  job: Pick<
    MigrationJob,
    'progressDone' | 'progressTotal' | 'progressFailed' | 'status'
  >,
): string {
  const failed =
    job.progressFailed > 0 ? `, ${n(job.progressFailed)} failed` : '';
  return `${fxMigrationCount(job)} processed${failed}`;
}
