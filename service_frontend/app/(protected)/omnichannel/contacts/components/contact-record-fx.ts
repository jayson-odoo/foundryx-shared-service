/**
 * Foundryx UIUX switch only (playbook-uiux.md, slice W1-CONTACT): the pure
 * pieces of the contact record under the new look, shared by its components
 * and tests. Nothing here runs with the switch off.
 *
 * The Details save builds its request with `contactDetailsPatch`, which
 * follows `contact-details-form.tsx`'s save line for line (only the keys the
 * person changed, empty text sent as null, custom fields as a partial merge,
 * phone never sent), so both looks send the same request for the same edit.
 */
import type {
  ContactField,
  ContactTagRef,
  ConversationThread,
  PatchContactInput,
} from '@/types/omnichannel';
import { fxBulkDoneWhat } from './contacts-fx';

export type CustomFieldValue = string | number | boolean | null;

export interface ContactSystemValues {
  firstName: string;
  lastName: string;
  email: string;
  language: string;
  countryCode: string;
}

export const CONTACT_SYSTEM_KEYS: (keyof ContactSystemValues)[] = [
  'firstName',
  'lastName',
  'email',
  'language',
  'countryCode',
];

export function contactSystemValues(
  thread: ConversationThread,
): ContactSystemValues {
  return {
    firstName: thread.firstName ?? '',
    lastName: thread.lastName ?? '',
    email: thread.email ?? '',
    language: thread.language ?? '',
    countryCode: thread.countryCode ?? '',
  };
}

export function contactCustomValues(
  thread: ConversationThread,
  fields: ContactField[],
): Record<string, CustomFieldValue> {
  const out: Record<string, CustomFieldValue> = {};
  for (const f of fields) {
    const raw = thread.customFields[f.key];
    out[f.key] = raw === undefined ? null : raw;
  }
  return out;
}

/** The PATCH a Details save sends: only what changed from `baseline`. */
export function contactDetailsPatch(
  system: ContactSystemValues,
  custom: Record<string, CustomFieldValue>,
  baseline: {
    system: ContactSystemValues;
    custom: Record<string, CustomFieldValue>;
  },
  fields: ContactField[],
): PatchContactInput {
  const before = baseline.system;
  const patch: PatchContactInput = {};
  if (system.firstName !== before.firstName)
    patch.firstName = system.firstName || null;
  if (system.lastName !== before.lastName)
    patch.lastName = system.lastName || null;
  if (system.email !== before.email) patch.email = system.email || null;
  if (system.language !== before.language)
    patch.language = system.language || null;
  if (system.countryCode !== before.countryCode)
    patch.countryCode = system.countryCode || null;

  const changedCustom: Record<string, CustomFieldValue> = {};
  let hasCustomChange = false;
  for (const f of fields) {
    if (custom[f.key] !== baseline.custom[f.key]) {
      changedCustom[f.key] = custom[f.key];
      hasCustomChange = true;
    }
  }
  if (hasCustomChange) patch.customFields = changedCustom;
  return patch;
}

/**
 * The PATCH that puts back what `patch` changed (the done toast's Undo),
 * through the same contact PATCH: each changed key gets its value from
 * before the save.
 */
export function contactDetailsUndoPatch(
  patch: PatchContactInput,
  baseline: {
    system: ContactSystemValues;
    custom: Record<string, CustomFieldValue>;
  },
): PatchContactInput {
  const undo: PatchContactInput = {};
  for (const key of CONTACT_SYSTEM_KEYS) {
    if (key in patch) undo[key] = baseline.system[key] || null;
  }
  if (patch.customFields) {
    const custom: Record<string, CustomFieldValue> = {};
    for (const key of Object.keys(patch.customFields))
      custom[key] = baseline.custom[key] ?? null;
    undo.customFields = custom;
  }
  return undo;
}

/** "AR" for "Aisyah binti Rahman": first and last word that start with a
 *  letter ("CC" for "Check Contact 17"). */
export function contactInitials(name: string): string {
  const all = name.trim().split(/\s+/).filter(Boolean);
  const lettered = all.filter((w) => w[0].toLowerCase() !== w[0].toUpperCase());
  const words = lettered.length ? lettered : all;
  if (!words.length) return '?';
  const first = words[0][0] ?? '';
  const last = words.length > 1 ? (words[words.length - 1][0] ?? '') : '';
  return (first + last).toUpperCase();
}

/** The tag ids after adding or removing one tag (same order as the chips). */
export function nextTagIds(
  current: ContactTagRef[],
  change: { add?: string; remove?: string },
): string[] {
  const ids = current.map((t) => t.id);
  if (change.add) return ids.includes(change.add) ? ids : [...ids, change.add];
  if (change.remove) return ids.filter((id) => id !== change.remove);
  return ids;
}

/** Done words for one contact's change (the list's words, one contact). */
export function contactTagDoneWhat(
  name: string,
  mode: 'add' | 'remove',
  tagName: string,
): string {
  return fxBulkDoneWhat(
    mode === 'add' ? 'add-tags' : 'remove-tags',
    [{ name }],
    [tagName],
  );
}

export function contactLifecycleDoneWhat(name: string, stage: string): string {
  return fxBulkDoneWhat('lifecycle', [{ name }], stage);
}

export function contactDetailsDoneWhat(name: string): string {
  return `${name}'s details updated`;
}

/** What the new contact is called once it exists, for its done toast. */
export function newContactName(values: {
  firstName: string;
  lastName: string;
  phone: string;
}): string {
  return (
    [values.firstName.trim(), values.lastName.trim()]
      .filter(Boolean)
      .join(' ') || values.phone.trim()
  );
}
