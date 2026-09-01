/** Shared display helpers for background jobs (generic, type-aware). */
import type { JobStatus, JobType } from '@/types/jobs';

/** Human label for a job type (extensible - falls back to a humanized key). */
export function jobTypeLabel(type: JobType): string {
  const known: Record<string, string> = {
    storage_migration: 'Storage migration',
  };
  return (
    known[type] ??
    type
      .split('_')
      .map((w) => (w ? w[0].toUpperCase() + w.slice(1) : w))
      .join(' ')
  );
}

/** Badge tone per status (maps to the shared Badge variants). */
export const JOB_STATUS_TONE: Record<
  JobStatus,
  'success' | 'destructive' | 'secondary' | 'primary' | 'warning'
> = {
  pending: 'secondary',
  running: 'primary',
  needs_review: 'warning',
  done: 'success',
  failed: 'destructive',
  aborted: 'secondary',
};

export const JOB_STATUS_LABEL: Record<JobStatus, string> = {
  pending: 'Pending',
  running: 'Running',
  needs_review: 'Needs review',
  done: 'Done',
  failed: 'Failed',
  aborted: 'Aborted',
};

/** Percent complete (0-100) for a job's progress bar. */
export function jobProgressPct(progressDone: number, progressTotal: number): number {
  if (progressTotal <= 0) return 0;
  return Math.min(100, Math.round((progressDone / progressTotal) * 100));
}
