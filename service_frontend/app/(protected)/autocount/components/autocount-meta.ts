import type { StatusRegistry } from '@/components/platform/status-badge';
import { humanizeFieldKey } from '@/lib/autocount-diff';
import { PRESETS, TRANSFORM_PRESET } from '@/lib/autocount-formula';
import type {
  AutocountEtlStatus,
  AutocountJobStatus,
  AutocountRunMode,
  AutocountRunOutcome,
  AutocountSourceImpl,
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

/** The task editor's tabs (plan 22 §3) - `?tab=` deep-links one. */
export type AcTaskTab = 'query' | 'mapping' | 'schedule' | 'activate' | 'runs';

/** The per-(company, entity) Database-mode task editor (plan 22, AC-22-07). */
export function acTaskHref(companyId: string, entityType: string, tab?: AcTaskTab): string {
  const base = `${AC_COMPANIES_PATH}/${companyId}/entities/${encodeURIComponent(entityType)}`;
  return tab && tab !== 'query' ? `${base}?tab=${tab}` : base;
}

// ── entity source (plan 22 S2, AC-22-08) ─────────────────────────────────────

/** The two sources an entity can read from - the picker's ONLY options. */
export const AC_SOURCE_IMPL_OPTIONS: { value: AutocountSourceImpl; label: string }[] = [
  { value: 'autocount_read', label: 'AutoCount API' },
  { value: 'sql_db', label: 'Database' },
];

export function sourceImplLabel(impl: string): string {
  return AC_SOURCE_IMPL_OPTIONS.find((o) => o.value === impl)?.label ?? humanizeFieldKey(impl);
}

/**
 * The entities backed by a confirmed, observed AutoCount API payload (mirrors
 * the backend's own `SEEDED_ENTITIES` guard, `services/company_service.py`) -
 * the ONLY entities the source-switch dialog may offer "AutoCount API" for.
 * The plan 22 S4 masters fan-out entities below have no vendor route at all,
 * so offering that option for them would be a guaranteed-to-fail sync
 * (foolproof-UI: only offer valid options).
 *
 * PARITY-PINNED (S4 review S2): `tests/test_autocount_entity_parity.py`
 * reads this literal straight out of this file and fails if it drifts from
 * `SEEDED_ENTITIES` - edit both sides together.
 */
export const AC_API_CAPABLE_ENTITY_TYPES: string[] = ['goods_received_note', 'supplier', 'customer'];

/**
 * The masters plan 22 S4 (AC-22-23) added, in DEPENDENCY order - categories
 * and units of measure before products (a product referencing an unsynced
 * category/UOM lands `retryable` until the dependency lands). This is the
 * Entities tab's "Add entity" picker's ONLY candidate list: every one of
 * these is DB-source only, so the task editor is where its config is born.
 */
export const AC_NEW_MASTER_ENTITY_TYPES: string[] = [
  'product_category',
  'unit_of_measure',
  'warehouse',
  'product',
  'sales_agent',
];

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
  // Plan 22 S5 - a document header ref field's named server-side transform
  // (see `lib/autocount-formula.ts` PRESETS for why this is a transform, not
  // a formula).
  ref_customer: 'ref_customer',
  ref_supplier: 'ref_supplier',
  ref_product: 'ref_product',
  ref_warehouse: 'ref_warehouse',
  ref_sales_agent: 'ref_sales_agent',
  custom: 'string',
};

/** The full preset catalog (Text/Boolean/Decimal/Integer/Date/the 5 ref
 *  presets/Custom), from the canonical `PRESETS` - NOT what any one row's
 *  Transform cell offers (see `presetOptionsForField`, S5 review BLOCKER 2
 *  FE half: a picker must offer ONLY valid options). */
export const AC_PRESET_OPTIONS: { value: string; label: string }[] = PRESETS.map((p) => ({
  value: p.key,
  label: p.label,
}));

/**
 * Sorento field → the ONE ref preset valid for it (mirrors the backend's
 * `mapping.FIELD_REF_TRANSFORMS`, S5 review BLOCKER 2). `product_ref`/
 * `warehouse_ref` are deliberately absent - those line fields are
 * code-generated (`document_line_rows`), never an operator-authored row.
 */
export const AC_FIELD_REF_PRESET: Record<string, string> = {
  customer_ref: 'ref_customer',
  supplier_ref: 'ref_supplier',
  sales_agent_ref: 'ref_sales_agent',
};

// ALL 5 ref presets (not just the 3 pairable to a field) - `ref_product`/
// `ref_warehouse` have no entry in `AC_FIELD_REF_PRESET` at all (their
// fields are never operator-mapped), but they must be excluded from every
// OTHER field's options exactly the same as the 3 that do.
const AC_REF_PRESET_KEYS = new Set(
  AC_PRESET_OPTIONS.filter((o) => o.value.startsWith('ref_')).map((o) => o.value),
);

/**
 * The Transform-preset options valid for a mapping row's CHOSEN Sorento
 * field (S5 review BLOCKER 2, FE half - foolproof-UI: only offer valid
 * options, the picker must never let an operator select a combination the
 * server rejects). A `*_ref` field offers ONLY its own matching ref preset;
 * every other field never sees a ref preset at all - the backend enforces
 * both directions (`company_service.replace_mapping`), this keeps the UI
 * from ever presenting the choice that would fail.
 */
export function presetOptionsForField(sorentoField: string): { value: string; label: string }[] {
  const refPreset = AC_FIELD_REF_PRESET[sorentoField];
  if (refPreset) {
    return AC_PRESET_OPTIONS.filter((o) => o.value === refPreset);
  }
  return AC_PRESET_OPTIONS.filter((o) => !AC_REF_PRESET_KEYS.has(o.value));
}

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
  SKIPPED: { label: 'Skipped', tone: 'secondary' },
};

/** How a run started (plan 22 §2.7) - the Runs tab's mode badge (AC-22-17). */
export const AC_RUN_MODE_REGISTRY: StatusRegistry<AutocountRunMode> = {
  manual: { label: 'Manual', tone: 'primary' },
  incremental: { label: 'Incremental', tone: 'success' },
  reconcile: { label: 'Reconcile', tone: 'info' },
  skipped: { label: 'Skipped', tone: 'warning' },
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
