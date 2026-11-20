/**
 * Deferred actions - the grace-window engine (sprint-4/23, T5, D2).
 *
 * Wire = camelCase, Z-suffixed datetimes (backend `app/schemas/pending_action.py`).
 * A destructive or reversible record action never opens a confirm dialog -
 * it PARKS here for its grace window; the button becomes a countdown with
 * Cancel, and the server applies it when the window lapses.
 */

export type DeferredActionWindow = 'destructive' | 'reversible';

/**
 * T5 fix round 2, B1: a row's countdown is `'pending'`; once the beat sweep
 * (or a racing `current` poll from another tab) CLAIMS it, it flips to
 * `'committing'` - still surfaced via `PendingActionCurrent.pending` (the
 * smallest wire change), never as a settled `lastOutcome` (anything short
 * of cancelled/failed there used to read as success).
 */
export type PendingActionRowStatus = 'pending' | 'committing';

export interface PendingAction {
  id: string;
  actionKey: string;
  entityType: string;
  entityId: string;
  commitAt: string; // ISO Z
  windowSeconds: number;
  requestedById: string | null;
  requestedByName: string | null;
  status: PendingActionRowStatus;
}

export type PendingActionOutcomeStatus = 'committed' | 'cancelled' | 'failed' | 'committing';

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
