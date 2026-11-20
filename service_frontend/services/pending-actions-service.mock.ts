/**
 * PHASE 1 MOCK deferred-actions service (sprint-4/23, T5) - an in-memory
 * pending-action store so the hook/button/toast can be tuned with NO
 * backend, and so `use-deferred-action.test.ts` can drive the state machine
 * with fake timers deterministically.
 *
 * DEBT: the shipped boundary is `pending-actions-service.real`; this exists
 * only for frontend-first iteration + Vitest. Never wired into a "done" slice.
 */
import type {
  PendingAction,
  PendingActionCreateResult,
  PendingActionOutcome,
} from '@/types/pending-actions';
import type { PendingActionsService } from './pending-actions-service';

const DEFAULT_WINDOW_SECONDS: Record<string, number> = {
  destructive: 10,
  reversible: 5,
};

function key(entityType: string, entityId: string): string {
  return `${entityType}:${entityId}`;
}

let _pending = new Map<string, PendingAction>();
let _lastOutcome = new Map<string, PendingActionOutcome>();
let _windowSecondsByKey: Record<string, number> = { ...DEFAULT_WINDOW_SECONDS };
let _seq = 0;

/** Test/dev seam - reset the mock store between tests. */
export function resetMockPendingActions(): void {
  _pending = new Map();
  _lastOutcome = new Map();
  _windowSecondsByKey = { ...DEFAULT_WINDOW_SECONDS };
  _seq = 0;
}

/** Test/dev seam - tune the mock window (mirrors a Settings > General edit). */
export function setMockWindowSeconds(window: 'destructive' | 'reversible', seconds: number): void {
  _windowSecondsByKey[window] = seconds;
}

/** Every registered action's window, for the mock's own park() resolution. */
const ACTION_WINDOWS: Record<string, 'destructive' | 'reversible'> = {
  'users.trash': 'destructive',
  'roles.delete': 'destructive',
  'workflows.delete': 'destructive',
  'forms.delete': 'destructive',
  'templates.delete': 'destructive',
  'connections.delete': 'destructive',
  'ai_agents.delete': 'destructive',
  'ai_skills.delete': 'destructive',
  'documents.trash': 'destructive',
  'tenants.archive': 'reversible',
};

function windowFor(actionKey: string): 'destructive' | 'reversible' {
  return ACTION_WINDOWS[actionKey] ?? 'destructive';
}

/** Lazily commit an overdue row (mirrors the backend's lazy-commit-on-read). */
function commitIfDue(k: string): void {
  const row = _pending.get(k);
  if (!row) return;
  if (Date.parse(row.commitAt) > Date.now()) return;
  _pending.delete(k);
  _lastOutcome.set(k, {
    id: row.id,
    actionKey: row.actionKey,
    status: 'committed',
    errorText: null,
    endedAt: new Date().toISOString(),
  });
}

export const mockPendingActionsService: PendingActionsService = {
  async park(actionKey, entityType, entityId) {
    const k = key(entityType, entityId);
    commitIfDue(k);
    const existing = _pending.get(k);
    if (existing) {
      if (existing.actionKey === actionKey) {
        return {
          id: existing.id,
          commitAt: existing.commitAt,
          windowSeconds: existing.windowSeconds,
        };
      }
      throw new Error('Another action on this record is still counting down.');
    }
    const windowSeconds = _windowSecondsByKey[windowFor(actionKey)];
    const row: PendingAction = {
      id: `pa-mock-${++_seq}`,
      actionKey,
      entityType,
      entityId,
      commitAt: new Date(Date.now() + windowSeconds * 1000).toISOString(),
      windowSeconds,
      requestedById: 'u-mock',
      requestedByName: 'You',
      status: 'pending',
    };
    _pending.set(k, row);
    const result: PendingActionCreateResult = {
      id: row.id,
      commitAt: row.commitAt,
      windowSeconds: row.windowSeconds,
    };
    return result;
  },
  async cancel(id) {
    for (const [k, row] of Array.from(_pending.entries())) {
      if (row.id === id) {
        commitIfDue(k);
        const stillPending = _pending.get(k);
        if (!stillPending || stillPending.id !== id) {
          throw new Error('The window already closed; the action was applied.');
        }
        _pending.delete(k);
        _lastOutcome.set(k, {
          id: row.id,
          actionKey: row.actionKey,
          status: 'cancelled',
          errorText: null,
          endedAt: new Date().toISOString(),
        });
        return { id, status: 'cancelled' };
      }
    }
    throw new Error('Pending action not found.');
  },
  async current(entityType, entityId) {
    const k = key(entityType, entityId);
    commitIfDue(k);
    return {
      pending: _pending.get(k) ?? null,
      lastOutcome: _lastOutcome.get(k) ?? null,
    };
  },
};
