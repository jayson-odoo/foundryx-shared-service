/**
 * AutoCount staged-record diff parsing + value formatting (AC-13-12).
 *
 * The backend's `compute_diff` (`modules/autocount/sync.py`) already emits
 * CHANGED FIELDS ONLY and deliberately excludes `last_modified` - it moves on
 * every fetch by definition, so surfacing it would make every record look
 * changed. Nothing here re-adds it, and the ignore set below is a mirror of the
 * backend's `DIFF_IGNORED_FIELDS` used ONLY when expanding a first-seen
 * record's canonical payload (where there is no server-computed diff to trust).
 */
import type {
  AutocountFieldChange,
  AutocountRecordDiff,
} from '@/types/autocount';

/** Sentinel the backend emits for a record it has never seen before. */
export const DIFF_NEW_KEY = '__new__';

/** Mirror of the backend `DIFF_IGNORED_FIELDS`. Never add `last_modified`. */
export const DIFF_IGNORED_FIELDS: ReadonlySet<string> = new Set([
  'last_modified',
  'last_modified_user_id',
  'source_system',
  'source_ref',
  'entity_type',
]);

/** A `{from, to}` entry as the backend writes it. */
function isChangeEntry(value: unknown): value is { from: unknown; to: unknown } {
  return (
    typeof value === 'object' &&
    value !== null &&
    !Array.isArray(value) &&
    ('from' in value || 'to' in value)
  );
}

/**
 * Parse a staged record's raw `diff` into the renderable view model.
 *
 * A null/empty diff yields NO changes - a record whose fields all matched is
 * not "everything changed", it is nothing changed.
 */
export function parseRecordDiff(
  diff: Record<string, unknown> | null | undefined,
): AutocountRecordDiff {
  if (!diff) return { isNew: false, changes: [] };

  if (diff[DIFF_NEW_KEY] === true) return { isNew: true, changes: [] };

  const changes: AutocountFieldChange[] = [];
  for (const [field, value] of Object.entries(diff)) {
    if (field === DIFF_NEW_KEY) continue;
    // A malformed entry is skipped rather than rendered as a bogus change -
    // an invented change is worse than a missing one on a review surface.
    if (!isChangeEntry(value)) continue;
    changes.push({ field, from: value.from, to: value.to });
  }
  changes.sort((a, b) => a.field.localeCompare(b.field));
  return { isNew: false, changes };
}

/** True for a value that carries nothing worth reviewing. */
function isEmptyValue(value: unknown): boolean {
  if (value === null || value === undefined || value === '') return true;
  if (Array.isArray(value)) return value.length === 0;
  if (typeof value === 'object') return Object.keys(value as object).length === 0;
  return false;
}

/**
 * The diff to render, given the raw diff and (for a first-seen record) its
 * canonical payload.
 *
 * For a NEW record the server sends only `{__new__: true}` - there is genuinely
 * no "before". Rather than show an empty review, its canonical fields are
 * expanded as `nothing → value`, which is exactly what will be pushed. Ignored
 * fields stay ignored on this path too.
 */
export function diffForDisplay(
  diff: Record<string, unknown> | null | undefined,
  canonical?: Record<string, unknown> | null,
): AutocountRecordDiff {
  const parsed = parseRecordDiff(diff);
  if (!parsed.isNew || !canonical) return parsed;

  const changes: AutocountFieldChange[] = [];
  for (const [field, value] of Object.entries(canonical)) {
    if (DIFF_IGNORED_FIELDS.has(field)) continue;
    if (isEmptyValue(value)) continue;
    changes.push({ field, from: undefined, to: value });
  }
  changes.sort((a, b) => a.field.localeCompare(b.field));
  return { isNew: true, changes };
}

/** `supplier_name` / `supplierName` → `Supplier name`. */
export function humanizeFieldKey(key: string): string {
  const spaced = key
    .replace(/[_.]+/g, ' ')
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .trim();
  if (!spaced) return key;
  return spaced.charAt(0).toUpperCase() + spaced.slice(1).toLowerCase();
}

/** How a diff value should be rendered. */
export interface DiffValueDisplay {
  /** `empty` = nothing there; `structured` = an object/array worth a code block. */
  kind: 'empty' | 'scalar' | 'structured';
  text: string;
}

/**
 * Format one side of a change for display. Structured values (a GRN's nested
 * `lines`, a customer's `extras` bag) are returned as pretty JSON so the
 * component can put them in their OWN scrollable block - never widening the
 * page.
 */
export function formatDiffValue(value: unknown): DiffValueDisplay {
  // An empty array/object reads as nothing, not as a `[]` code block - "no
  // lines → 3 lines" is the useful rendering of an added collection.
  if (isEmptyValue(value)) {
    return { kind: 'empty', text: '-' };
  }
  if (typeof value === 'boolean') {
    return { kind: 'scalar', text: value ? 'Yes' : 'No' };
  }
  if (typeof value === 'number' || typeof value === 'string') {
    return { kind: 'scalar', text: String(value) };
  }
  try {
    return { kind: 'structured', text: JSON.stringify(value, null, 2) };
  } catch {
    return { kind: 'scalar', text: String(value) };
  }
}
