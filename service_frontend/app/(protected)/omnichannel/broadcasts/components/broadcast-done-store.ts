/**
 * The broadcast that was just sent or scheduled from this tab, for the done
 * page under the Foundryx UIUX switch (answers Q3). In memory only: a reload
 * or a shared link opens the ordinary broadcast page, because only the person
 * who pressed Send in this tab knows that it was them ("by whom" is not
 * stored by the backend).
 */
export interface BroadcastDoneEntry {
  mode: 'now' | 'schedule';
  /** The person who pressed Send (the signed-in user). */
  byWhom: string | null;
  /** The recipient count the form showed when it was sent. */
  audienceCount: number | null;
  /** When Send was pressed (ISO), used when the backend has no time yet. */
  pressedAt: string;
}

const entries = new Map<string, BroadcastDoneEntry>();

export function setBroadcastDone(id: string, entry: BroadcastDoneEntry): void {
  entries.set(id, entry);
}

export function peekBroadcastDone(id: string): BroadcastDoneEntry | null {
  return entries.get(id) ?? null;
}

export function clearBroadcastDone(id: string): void {
  entries.delete(id);
}
