/**
 * The set of entity ids currently parked under a deferred action (sprint-4/23
 * T5, AC-DLA-45) - a tiny module-level pub/sub, NOT React state, so a row's
 * dimming survives whichever component started the park (a row's own
 * ActionMenu, or a BulkActions toolbar) unmounting before the window closes.
 * `components/ui/data-grid-table.tsx`'s `useRowPendingDim` subscribes and
 * imperatively toggles `data-pending` on the matching `[data-row-id]`
 * elements - the same "DOM attribute, not a re-render" pattern
 * `useRestoreReturnedRow` already uses for `data-returned`.
 */
type Listener = () => void;

const _ids = new Set<string>();
const _listeners = new Set<Listener>();

function notify(): void {
  for (const listener of Array.from(_listeners)) listener();
}

export function trackPendingEntities(ids: readonly string[]): void {
  for (const id of ids) _ids.add(id);
  notify();
}

export function untrackPendingEntities(ids: readonly string[]): void {
  for (const id of ids) _ids.delete(id);
  notify();
}

export function isPendingEntity(id: string): boolean {
  return _ids.has(id);
}

export function pendingEntityIds(): ReadonlySet<string> {
  return _ids;
}

export function subscribePendingEntities(listener: Listener): () => void {
  _listeners.add(listener);
  return () => _listeners.delete(listener);
}

/** Test-only seam. */
export function _resetPendingEntityStoreForTests(): void {
  _ids.clear();
}
