import type { StatusRegistry } from '@/components/platform/status-badge';
import type { MigrationSyncStatus } from '@/types/respondio-migration';

/** Continuous-sync lifecycle pills (plan 52) - frontend-only registry. */
export const SYNC_STATUS_REGISTRY: StatusRegistry<MigrationSyncStatus> = {
  active: { label: 'Active', tone: 'success' },
  paused: { label: 'Paused', tone: 'warning' },
  stopping: { label: 'Stopping', tone: 'info' },
  stopped: { label: 'Stopped', tone: 'secondary' },
};

/** Paused reason copy (AC-SYNC-52). `manual` has no extra line. */
export const SYNC_PAUSED_REASON_TEXT: Record<string, string> = {
  token_rejected: 'respond.io rejected the access token',
  connection_missing: 'The respond.io connection no longer exists',
  workspace_missing: 'The workspace no longer exists',
};

/** AC-SYNC-50: the sync card is offered only on a finished real API run. */
export function canOfferSync(job: { mode: string; source: string; status: string }): boolean {
  return job.mode === 'run' && job.source === 'api' && job.status === 'done';
}
