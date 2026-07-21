import type { StatusRegistry } from '@/components/platform/status-badge';
import { humanizeFieldKey } from '@/lib/autocount-diff';
import type {
  AutocountJobStatus,
  AutocountRunOutcome,
  AutocountStagedStatus,
} from '@/types/autocount';

// ── permission keys (module CSV: modules/autocount/permissions/permissions.csv)
export const AC_COMPANIES_READ = 'autocount.companies.read';
export const AC_COMPANIES_MANAGE = 'autocount.companies.manage';
export const AC_SYNC_READ = 'autocount.sync.read';
export const AC_SYNC_RUN = 'autocount.sync.run';

// ── routes ───────────────────────────────────────────────────────────────────
export const AC_COMPANIES_PATH = '/autocount/companies';
export const AC_COMPANY_NEW_PATH = '/autocount/companies/new';

export function acCompanyHref(id: string): string {
  return `${AC_COMPANIES_PATH}/${id}`;
}

export function acReviewHref(jobId: string, from?: string): string {
  const suffix = from ? `?from=${encodeURIComponent(from)}` : '';
  return `/autocount/review/${jobId}${suffix}`;
}

// ── labels ───────────────────────────────────────────────────────────────────

/**
 * Canonical entity key → display label. Derived, never a hardcoded lookup of a
 * tenant-editable key: these keys are CODE constants (`ENTITY_GOODS_RECEIVED_NOTE`),
 * not renameable configuration.
 */
export function entityLabel(entityType: string): string {
  return humanizeFieldKey(entityType);
}

export function syncModeLabel(mode: string): string {
  if (mode === 'SCHEDULED_REVIEW') return 'Review before push';
  if (mode === 'AUTO') return 'Automatic';
  if (mode === 'MANUAL') return 'Manual';
  return humanizeFieldKey(mode);
}

// ── status registries ────────────────────────────────────────────────────────

export const AC_RUN_OUTCOME_REGISTRY: StatusRegistry<AutocountRunOutcome> = {
  SUCCESS: { label: 'Success', tone: 'success' },
  FAILED: { label: 'Failed', tone: 'destructive' },
  ABORTED: { label: 'Aborted', tone: 'warning' },
};

export const AC_JOB_STATUS_REGISTRY: StatusRegistry<AutocountJobStatus> = {
  pending: { label: 'Pending', tone: 'secondary' },
  running: { label: 'Running', tone: 'info' },
  needs_review: { label: 'Needs review', tone: 'warning' },
  done: { label: 'Done', tone: 'success' },
  failed: { label: 'Failed', tone: 'destructive' },
  aborted: { label: 'Aborted', tone: 'secondary' },
};

export const AC_STAGED_STATUS_REGISTRY: StatusRegistry<AutocountStagedStatus> = {
  STAGED: { label: 'Awaiting approval', tone: 'warning' },
  FAILED: { label: 'Failed', tone: 'destructive' },
  PUSHED: { label: 'Pushed', tone: 'success' },
  DISCARDED: { label: 'Discarded', tone: 'secondary' },
};
