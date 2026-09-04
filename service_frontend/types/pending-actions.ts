/**
 * Deferred actions - the grace-window engine (sprint-4/23, T5, D2).
 *
 * Wire = camelCase, Z-suffixed datetimes (backend `app/schemas/pending_action.py`).
 * A destructive or reversible record action never opens a confirm dialog -
 * it PARKS here for its grace window; the button becomes a countdown with
 * Cancel, and the server applies it when the window lapses.
 */

export type DeferredActionWindow = 'destructive' | 'reversible';

export interface PendingAction {
  id: string;
  actionKey: string;
  entityType: string;
  entityId: string;
  commitAt: string; // ISO Z
  windowSeconds: number;
  requestedById: string | null;
  requestedByName: string | null;
}

export type PendingActionOutcomeStatus = 'committed' | 'cancelled' | 'failed';

export interface PendingActionOutcome {
  id: string;
  actionKey: string;
  status: PendingActionOutcomeStatus;
  errorText: string | null;
  endedAt: string | null; // ISO Z
}

export interface PendingActionCurrent {
  pending: PendingAction | null;
  lastOutcome: PendingActionOutcome | null;
}

export interface PendingActionCreateResult {
  id: string;
  commitAt: string; // ISO Z
  windowSeconds: number;
}
