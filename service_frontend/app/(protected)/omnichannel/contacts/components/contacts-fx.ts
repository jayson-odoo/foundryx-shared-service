/**
 * Foundryx UIUX switch only (playbook-uiux.md, slice W1-CONTACTS): the words
 * the Contacts list uses with the switch on, and the plans that undo a bulk
 * change through the existing bulk API. Pure, so the page, its dialogs and
 * the tests share them. Nothing here runs with the switch off.
 */
import { createContext, useContext } from 'react';
import { SessionContext } from 'next-auth/react';
import type { ContactListItem } from '@/types/omnichannel';
import { fxCount } from '@/components/fx/list/fx-words';

/** "1 contact" / "1,240 contacts". */
export function fxContacts(n: number): string {
  return `${fxCount(n)} ${n === 1 ? 'contact' : 'contacts'}`;
}

/** "1 contact's" / "12 contacts'" (a field that belongs to them). */
function fxContactsOwn(n: number): string {
  return n === 1 ? `${fxCount(n)} contact's` : `${fxCount(n)} contacts'`;
}

export type FxBulkKind = 'assign' | 'add-tags' | 'remove-tags' | 'lifecycle';

/**
 * A bulk panel names the field it changes and its action says how many rows
 * it changes (playbook "Changing many at once"): "Update 12 contacts'
 * lifecycle".
 */
export function fxBulkPanelWords(
  kind: FxBulkKind,
  n: number,
): { title: string; field: string; action: string } {
  switch (kind) {
    case 'assign':
      return {
        title: 'Assignee',
        field: 'Assign to',
        action: `Update ${fxContactsOwn(n)} assignee`,
      };
    case 'add-tags':
      return {
        title: 'Tags to add',
        field: 'Tags to add',
        action: `Add tags to ${fxContacts(n)}`,
      };
    case 'remove-tags':
      return {
        title: 'Tags to remove',
        field: 'Tags to remove',
        action: `Remove tags from ${fxContacts(n)}`,
      };
    case 'lifecycle':
      return {
        title: 'Lifecycle stage',
        field: 'Move to stage',
        action: `Update ${fxContactsOwn(n)} lifecycle`,
      };
  }
}

const quoted = (names: string[]) => names.map((name) => `"${name}"`).join(', ');

/**
 * What a finished bulk change says (playbook "Done"): one contact is named,
 * more are counted. `target` is the assignee, the tag names or the stage.
 */
export function fxBulkDoneWhat(
  kind: FxBulkKind,
  okRows: Pick<ContactListItem, 'name'>[],
  target: string | string[] | null,
): string {
  const who = okRows.length === 1 ? okRows[0].name : fxContacts(okRows.length);
  const tags = Array.isArray(target) ? target : target ? [target] : [];
  switch (kind) {
    case 'assign':
      return target
        ? `${who} assigned to ${target as string}`
        : `${who} unassigned`;
    case 'add-tags':
      return `${tags.length === 1 ? 'Tag' : 'Tags'} ${quoted(tags)} added to ${who}`;
    case 'remove-tags':
      return `${tags.length === 1 ? 'Tag' : 'Tags'} ${quoted(tags)} removed from ${who}`;
    case 'lifecycle':
      return `${who} moved to ${target as string}`;
  }
}

/** One call to the bulk assign API that puts some contacts back. */
export interface FxAssignUndoStep {
  ids: string[];
  assigneeUserId: string | null;
}

/** Undo for a bulk assign: each changed contact back to its old assignee,
 *  one call per old assignee. Contacts whose assignee did not change are left. */
export function fxAssignUndoPlan(
  rows: Pick<ContactListItem, 'id' | 'assignedUserId'>[],
  okIds: string[],
  newAssigneeUserId: string | null,
): FxAssignUndoStep[] {
  const ok = new Set(okIds);
  const byPrev = new Map<string | null, string[]>();
  for (const row of rows) {
    if (!ok.has(row.id)) continue;
    const prev = row.assignedUserId ?? null;
    if (prev === newAssigneeUserId) continue;
    byPrev.set(prev, [...(byPrev.get(prev) ?? []), row.id]);
  }
  return Array.from(byPrev, ([assigneeUserId, ids]) => ({
    ids,
    assigneeUserId,
  }));
}

/** One call to the bulk tags API that puts some tags back. */
export interface FxTagsUndoStep {
  ids: string[];
  mode: 'add' | 'remove';
  tagIds: string[];
}

/** Undo for a bulk tag change: an added tag comes off only the contacts that
 *  did not have it; a removed tag goes back only on those that had it. */
export function fxTagsUndoPlan(
  rows: Pick<ContactListItem, 'id' | 'tags'>[],
  okIds: string[],
  mode: 'add' | 'remove',
  tagIds: string[],
): FxTagsUndoStep[] {
  const ok = new Set(okIds);
  const steps: FxTagsUndoStep[] = [];
  for (const tagId of tagIds) {
    const ids = rows
      .filter((row) => ok.has(row.id))
      .filter((row) => {
        const had = row.tags.some((t) => t.id === tagId);
        return mode === 'add' ? !had : had;
      })
      .map((row) => row.id);
    if (ids.length)
      steps.push({
        ids,
        mode: mode === 'add' ? 'remove' : 'add',
        tagIds: [tagId],
      });
  }
  return steps;
}

/**
 * The export hand-off toast (gap audit 2): where the export went on.
 * `count` is unknown when the list total is not known yet.
 */
export function fxExportPendingWords(count: number | null): string {
  const what =
    count === null
      ? 'The export of the contacts'
      : `The export of ${fxContacts(count)}`;
  return `${what} is still running. It will be in Jobs.`;
}

/** The signed-in person's name, for "by Kay" in done toasts. Reads the
 *  session context directly so it is safe where no session is mounted. */
const NO_SESSION = createContext<
  { data?: { user?: { name?: string | null } } | null } | undefined
>(undefined);

function sessionContext(): typeof NO_SESSION {
  try {
    return (SessionContext as typeof NO_SESSION | undefined) ?? NO_SESSION;
  } catch {
    // A test double of next-auth without the context.
    return NO_SESSION;
  }
}
const SESSION = sessionContext();

export function useFxActorName(): string | undefined {
  const session = useContext(SESSION);
  return session?.data?.user?.name ?? undefined;
}
