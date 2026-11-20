/**
 * Migration job detail progress bar (review round 2, R2) - pure so it is
 * unit-testable without rendering the whole `[jobId]/page.tsx` (the
 * `migration-status.ts` precedent for a frontend-only pure helper next to a
 * registry). The backend's `progressTotal` is a monotonic RUNNING estimate
 * during a job (`checkpoint()`'s own `max(...)` note in
 * `migration_service.py`) and can transiently trail `progressDone` by a
 * beat before the next checkpoint catches up - this clamps the DISPLAYED
 * percentage to 100 so the bar/label never reads over-full while a job is
 * still genuinely running.
 */
export function migrationProgressPct(progressDone: number, progressTotal: number): number {
  if (progressTotal <= 0) {
    return 0;
  }
  return Math.min(100, Math.round((progressDone / progressTotal) * 100));
}
