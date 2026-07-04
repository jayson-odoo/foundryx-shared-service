/**
 * Pure RBAC key helpers (plan 03 §2.4). The implied-read rule — *any* granted
 * action on a resource implies `<resource>.read` — is enforced here so the UI
 * lock and the (eventual) server normalization share one definition. Framework-
 * agnostic + side-effect-free so it's trivially unit-testable.
 */

/** Split a flat key `"<resource>.<action>"` into its parts (resource has no dot). */
export function splitKey(key: string): { resource: string; action: string } {
  const i = key.indexOf('.');
  if (i === -1) return { resource: key, action: '' };
  return { resource: key.slice(0, i), action: key.slice(i + 1) };
}

export function resourceOf(key: string): string {
  return splitKey(key).resource;
}

export function actionOf(key: string): string {
  return splitKey(key).action;
}

/** The read key for a resource. */
export function readKeyFor(resource: string): string {
  return `${resource}.read`;
}

/** Keys belonging to one resource (the subset a resource dropdown owns). */
export function keysForResource(keys: string[], resource: string): string[] {
  return keys.filter((k) => resourceOf(k) === resource);
}

/**
 * Blanket implied-read over a single resource's selection: if any non-read
 * action is present, force `<resource>.read` in. Order-stable, de-duplicated.
 */
export function normalizeResourceGrants(resource: string, selection: string[]): string[] {
  const set = new Set(selection.filter((k) => resourceOf(k) === resource));
  const hasWrite = Array.from(set).some((k) => actionOf(k) !== 'read');
  if (hasWrite) set.add(readKeyFor(resource));
  return Array.from(set);
}

/**
 * Apply implied-read across a full grant set (every resource independently).
 * This is the storage-guarantee shape the backend mirrors on save.
 */
export function applyImpliedRead(keys: string[]): string[] {
  const set = new Set(keys);
  const writesByResource = new Set<string>();
  for (const k of keys) {
    if (actionOf(k) !== 'read') writesByResource.add(resourceOf(k));
  }
  writesByResource.forEach((resource) => set.add(readKeyFor(resource)));
  return Array.from(set);
}

/**
 * Replace one resource's slice of a full grant set with a new (normalized)
 * selection, leaving every other resource's keys untouched. Used by the
 * per-resource dropdown to write back into the form's flat `permissionKeys`.
 */
export function mergeResourceGrants(
  allKeys: string[],
  resource: string,
  selection: string[],
): string[] {
  const others = allKeys.filter((k) => resourceOf(k) !== resource);
  return [...others, ...normalizeResourceGrants(resource, selection)];
}
