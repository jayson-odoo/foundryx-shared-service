import type { StatusRegistry } from '@/components/platform/status-badge';
import type { MigrationJobStatus, MigrationMode } from '@/types/respondio-migration';

/**
 * Migration job lifecycle pills (plan 33 S0) - a frontend-only registry over
 * the generic `background_jobs` status the job rides (mirrors
 * `broadcast-status.ts` / `template-status.ts`), not a core status-engine
 * scope.
 */
export const MIGRATION_STATUS_REGISTRY: StatusRegistry<MigrationJobStatus> = {
  pending: { label: 'Pending', tone: 'secondary' },
  running: { label: 'Running', tone: 'info' },
  needs_review: { label: 'Needs review', tone: 'warning' },
  done: { label: 'Done', tone: 'success' },
  failed: { label: 'Failed', tone: 'destructive' },
  aborted: { label: 'Aborted', tone: 'secondary' },
};

export const MIGRATION_STATUS_SEGMENTS: { id: string; label: string }[] = [
  { id: 'all', label: 'All' },
  { id: 'pending', label: 'Pending' },
  { id: 'running', label: 'Running' },
  { id: 'needs_review', label: 'Needs review' },
  { id: 'done', label: 'Done' },
  { id: 'failed', label: 'Failed' },
  { id: 'aborted', label: 'Aborted' },
];

export const MIGRATION_MODE_LABEL: Record<MigrationMode, string> = {
  dry_run: 'Dry run',
  run: 'Migration',
};
