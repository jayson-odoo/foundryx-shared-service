/**
 * The role permission grid under the Foundryx UIUX switch writes the grant set
 * through these, built only from what today's per-resource dropdown does, so
 * the same ticks always send the same `permissionKeys`:
 * - one action: added at the end of the resource's selection, or removed
 *   (the dropdown's `toggle`);
 * - All: every action in catalog order, or none once all are on (the
 *   dropdown's "Select all" / "Clear all");
 * - both then go through `mergeResourceGrants`, which applies implied read.
 */
import { actionOf, keysForResource, mergeResourceGrants } from '@/lib/permissions';
import type { PermissionResource } from '@/types/permission';

/** The grant set after ticking or unticking one action of `resource`. */
export function toggleResourceAction(
  allKeys: string[],
  resource: PermissionResource,
  key: string,
): string[] {
  const selected = keysForResource(allKeys, resource.resource);
  const next = selected.includes(key) ? selected.filter((k) => k !== key) : [...selected, key];
  return mergeResourceGrants(allKeys, resource.resource, next);
}

/** True when the dropdown would offer "Clear all" for `resource`. */
export function allResourceActionsOn(allKeys: string[], resource: PermissionResource): boolean {
  const selected = keysForResource(allKeys, resource.resource);
  return resource.actions.length > 0 && selected.length === resource.actions.length;
}

/** The grant set after the row's All tick: every action, or none once all are on. */
export function toggleAllResourceActions(allKeys: string[], resource: PermissionResource): string[] {
  const next = allResourceActionsOn(allKeys, resource) ? [] : resource.actions.map((a) => a.key);
  return mergeResourceGrants(allKeys, resource.resource, next);
}

/**
 * True when `key` is the resource's read and another of its actions is on:
 * implied read keeps it on, so its tick is shown on and greyed (unticking it
 * would change nothing).
 */
export function isImpliedRead(allKeys: string[], resource: PermissionResource, key: string): boolean {
  if (actionOf(key) !== 'read') return false;
  return keysForResource(allKeys, resource.resource).some((k) => actionOf(k) !== 'read');
}
