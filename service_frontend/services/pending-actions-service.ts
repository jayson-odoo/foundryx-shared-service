/**
 * Deferred-actions service (sprint-4/23, T5) - the boundary
 * `hooks/use-deferred-action.ts` talks to. Three calls, matching the backend
 * contract 1:1 (`app/api/v1/pending_actions.py`):
 *
 *   park(actionKey, entityType, entityId, payload?)  -> POST /api/v1/pending-actions (202)
 *   cancel(id)                                       -> POST /api/v1/pending-actions/{id}/cancel
 *   current(entityType, entityId)                    -> GET  /api/v1/pending-actions/current
 *
 * Frontend-first: iterated against `.mock` (tunable pending/committed/failed
 * states, no backend); the shipped boundary below is the `.real` api-client
 * impl - the mock/real swap is this one line (PHASE 2, done).
 */
import type {
  DeferredActionWindow,
  PendingActionCreateResult,
  PendingActionCurrent,
} from '@/types/pending-actions';
import { realPendingActionsService } from './pending-actions-service.real';

export interface PendingActionsService {
  park(
    actionKey: string,
    entityType: string,
    entityId: string,
    payload?: Record<string, unknown>,
  ): Promise<PendingActionCreateResult>;
  cancel(id: string): Promise<{ id: string; status: string }>;
  current(entityType: string, entityId: string): Promise<PendingActionCurrent>;
}

// Re-exported so callers building a `deferred` config can reuse the literal
// union without importing the types module directly.
export type { DeferredActionWindow };

// Phase-B swap: the real api-client impl is the shipped boundary.
export const pendingActionsService: PendingActionsService = realPendingActionsService;
