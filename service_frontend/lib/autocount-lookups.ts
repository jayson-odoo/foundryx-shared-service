/**
 * Lookups editor helpers (sprint-5/10, R9/AC-10-01) - pure, shared by the
 * Source tab's Lookups section. No React, no fetch. Mirrors the backend's
 * save-time guard (`http_source/lookups.py::validate_lookups`) client-side
 * so the inline 422 shows before a save round trip, never only after one.
 */
import type { AutocountLookupField, AutocountLookupSpec } from '@/types/autocount';

/** Mirrors `validate_http_path` (`http_source/preview.py:30-46`) - the
 * lookup editor can never reach an endpoint the main path could not. */
export function validateLookupPath(path: string): string | null {
  const trimmed = path.trim();
  if (!trimmed) return 'Enter an endpoint path.';
  if (!trimmed.startsWith('/')) return 'Path must start with /.';
  if (trimmed.includes('..')) return 'Path must not contain "..".';
  if (trimmed.includes('?')) return 'Path must not carry a query string.';
  if (trimmed.length > 200) return 'Path must be 200 characters or fewer.';
  return null;
}

/** `as` (the lookup's own name) and every `fields[].as` (AC-10-01). */
export const LOOKUP_ALIAS_RE = /^[A-Za-z][A-Za-z0-9_]{0,40}$/;

export function validateAliasFormat(alias: string): string | null {
  if (!alias.trim()) return 'Name the field.';
  if (!LOOKUP_ALIAS_RE.test(alias)) {
    return 'Use letters, digits and underscore only, starting with a letter (max 41 characters).';
  }
  return null;
}

export const MAX_LOOKUPS = 5;

/** A fresh, empty lookup row - the Add-lookup affordance's starting point. */
export function emptyLookup(index: number): AutocountLookupSpec {
  return { path: '', as: `lookup${index + 1}`, on: [{ local: '', remote: '' }], fields: [] };
}

/**
 * Every alias a lookup at `index` may legally name a `local` join column
 * from, or that must not collide with a NEW alias at this index (AC-10-01/
 * AC-10-02): the source columns plus every EARLIER lookup's own delivered
 * aliases (`fields[].as`), in evaluation order.
 */
export function earlierAliases(lookups: AutocountLookupSpec[], index: number): string[] {
  const out: string[] = [];
  for (let i = 0; i < index; i += 1) {
    for (const field of lookups[i]?.fields ?? []) {
      if (field.as.trim()) out.push(field.as.trim());
    }
  }
  return out;
}

/**
 * Every alias already claimed by lookup index `index` or an EARLIER one -
 * the exact set a NEW alias at this index must avoid (AC-10-01: "an alias
 * colliding with a source column or with an earlier lookup's alias").
 * Aliases from a LATER lookup are deliberately excluded - editing THIS
 * lookup's fields never invalidates a later one that already named it
 * (evaluation order, not save order).
 */
export function claimedAliasesUpTo(
  lookups: AutocountLookupSpec[],
  index: number,
  excludeFieldIndex?: number,
): string[] {
  const out = earlierAliases(lookups, index);
  (lookups[index]?.fields ?? []).forEach((field: AutocountLookupField, i) => {
    if (i === excludeFieldIndex) return;
    if (field.as.trim()) out.push(field.as.trim());
  });
  return out;
}

/**
 * One field row's alias 422, mirroring the backend save-time gate: a
 * collision with a source column, an earlier lookup's alias, or a sibling
 * field at the SAME lookup.
 */
export function aliasCollision(
  alias: string,
  sourceColumns: string[],
  lookups: AutocountLookupSpec[],
  lookupIndex: number,
  fieldIndex: number,
): string | null {
  const format = validateAliasFormat(alias);
  if (format) return format;
  const trimmed = alias.trim();
  if (sourceColumns.includes(trimmed)) {
    return `"${trimmed}" is already a source column.`;
  }
  if (claimedAliasesUpTo(lookups, lookupIndex, fieldIndex).includes(trimmed)) {
    return `"${trimmed}" is already used by another lookup field.`;
  }
  return null;
}

/** `local` options for a join pair at `lookupIndex` - source columns plus
 * every earlier lookup's own aliases (multi-hop, AC-10-02). */
export function localColumnOptions(sourceColumns: string[], lookups: AutocountLookupSpec[], lookupIndex: number): string[] {
  return Array.from(new Set([...sourceColumns, ...earlierAliases(lookups, lookupIndex)]));
}

/** A lookup's Test button is enabled once it names a path (join pairs and
 * fields may still be empty - the Test itself probes columns to pick from). */
export function canTestLookup(lookup: AutocountLookupSpec): boolean {
  return validateLookupPath(lookup.path) === null;
}
