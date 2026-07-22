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
export const AC_REVIEW_PATH = '/autocount/review';

export function acCompanyHref(id: string): string {
  return `${AC_COMPANIES_PATH}/${id}`;
}

export function acReviewHref(jobId: string, from?: string): string {
  const suffix = from ? `?from=${encodeURIComponent(from)}` : '';
  return `${AC_REVIEW_PATH}/${jobId}${suffix}`;
}

/** The per-(company, entity) field-mapping editor (AC-15-40). */
export function acMappingHref(companyId: string, entityType: string): string {
  return `${AC_COMPANIES_PATH}/${companyId}/entities/${encodeURIComponent(entityType)}/mapping`;
}

// ── transforms (mapping editor picker; mirrors backend mapping.py TRANSFORMS) ──

/**
 * The known field transforms an operator may pick in the mapping editor. Mirror
 * of the backend `TRANSFORMS` registry (`modules/autocount/mapping.py`) — the
 * PUT guard rejects an unknown transform, so only these are offered (foolproof).
 */
export const AC_TRANSFORMS: { value: string; label: string }[] = [
  { value: 'string', label: 'Text' },
  { value: 'bool', label: 'Boolean' },
  { value: 't_f_bool', label: 'T / F flag → Boolean' },
  { value: 'int', label: 'Whole number' },
  { value: 'decimal', label: 'Decimal' },
  { value: 'date', label: 'Date' },
  { value: 'datetime', label: 'Date & time' },
  { value: 'slash_datetime', label: 'Slash date/time' },
];

export function transformLabel(transform: string): string {
  return AC_TRANSFORMS.find((t) => t.value === transform)?.label ?? humanizeFieldKey(transform);
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
