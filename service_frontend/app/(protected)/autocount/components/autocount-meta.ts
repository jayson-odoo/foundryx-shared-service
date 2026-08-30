import type { StatusRegistry } from '@/components/platform/status-badge';
import { humanizeFieldKey } from '@/lib/autocount-diff';
import { PRESETS, TRANSFORM_PRESET } from '@/lib/autocount-formula';
import type {
  AutocountEtlStatus,
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

/** The per-(company, entity) Database-mode task editor (plan 22, AC-22-07). */
export function acTaskHref(companyId: string, entityType: string): string {
  return `${AC_COMPANIES_PATH}/${companyId}/entities/${encodeURIComponent(entityType)}`;
}

// ── transforms (mapping editor picker; mirrors backend mapping.py TRANSFORMS) ──

/**
 * The known field transforms an operator may pick in the mapping editor. Mirror
 * of the backend `TRANSFORMS` registry (`modules/autocount/mapping.py`) - the
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

// ── formula presets (slice 16, AC-16-10) ──────────────────────────────────────

/**
 * Preset key → the named transform stored alongside a row for back-compat and as
 * the formula-NULL fallback path. A row always carries a named transform; a
 * non-empty `formula` overrides it (`lib/autocount-formula.ts`).
 */
export const AC_PRESET_TRANSFORM: Record<string, string> = {
  text: 'string',
  boolean: 't_f_bool',
  decimal: 'decimal',
  integer: 'int',
  date: 'slash_datetime',
  custom: 'string',
};

/** The 6 presets offered in the Transform cell (Text/Boolean/Decimal/Integer/
 *  Date/Custom) - the picker's option list, from the canonical `PRESETS`. */
export const AC_PRESET_OPTIONS: { value: string; label: string }[] = PRESETS.map((p) => ({
  value: p.key,
  label: p.label,
}));

/** The canonical formula for a preset (the Build dialog pre-fills from it). */
export function presetFormula(key: string): string {
  return PRESETS.find((p) => p.key === key)?.formula ?? '';
}

/**
 * Derive which preset a row currently reflects: from its named transform, but a
 * formula that DIVERGES from that preset's canonical expression reads as Custom -
 * so an edited/authored formula is never mislabelled as a stock preset.
 */
export function presetForRow(transform: string, formula: string | null): string {
  const base = TRANSFORM_PRESET[transform] ?? 'custom';
  const f = formula?.trim();
  if (f && f !== presetFormula(base).trim()) return 'custom';
  return base;
}

/**
 * What choosing a preset writes to a row (AC-16-10). Fills the formula for the
 * non-trivial transforms the operator wants to EXPRESS (boolean/integer/date -
 * incl. the stated `if(value == "T", …)`); the trivial Text passthrough and the
 * precision-sensitive Decimal keep their EXACT named transform with no formula
 * (so simple rows stay clutter-free and money keeps exact precision - the Build
 * dialog still pre-fills their canonical formula for opt-in editing).
 */
export function applyPreset(key: string): { transform: string; formula: string | null } {
  const transform = AC_PRESET_TRANSFORM[key] ?? 'string';
  if (key === 'boolean' || key === 'integer' || key === 'date') {
    return { transform, formula: presetFormula(key) };
  }
  if (key === 'custom') return { transform, formula: '' };
  return { transform, formula: null };
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

/** DB extraction task lifecycle (plan 22 §2.4 `etl_status`). */
export const AC_ETL_STATUS_REGISTRY: StatusRegistry<AutocountEtlStatus> = {
  draft: { label: 'Draft', tone: 'secondary' },
  active: { label: 'Active', tone: 'success' },
  paused: { label: 'Paused', tone: 'warning' },
};

export const AC_STAGED_STATUS_REGISTRY: StatusRegistry<AutocountStagedStatus> = {
  STAGED: { label: 'Awaiting approval', tone: 'warning' },
  FAILED: { label: 'Failed', tone: 'destructive' },
  PUSHED: { label: 'Pushed', tone: 'success' },
  DISCARDED: { label: 'Discarded', tone: 'secondary' },
};
