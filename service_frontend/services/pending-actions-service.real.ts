import { apiFetch } from '@/lib/api-client';
import type {
  PendingActionCreateResult,
  PendingActionCurrent,
} from '@/types/pending-actions';
import type { PendingActionsService } from './pending-actions-service';

export const realPendingActionsService: PendingActionsService = {
  park(actionKey, entityType, entityId, payload) {
    return apiFetch<PendingActionCreateResult>('/api/v1/pending-actions', {
      method: 'POST',
      body: JSON.stringify({
        actionKey,
        entityType,
        entityId,
        payload: payload ?? undefined,
      }),
    });
  },
  cancel(id) {
    return apiFetch<{ id: string; status: string }>(
      `/api/v1/pending-actions/${id}/cancel`,
      { method: 'POST' },
    );
  },
  current(entityType, entityId) {
    const p = new URLSearchParams({ entityType, entityId });
    return apiFetch<PendingActionCurrent>(`/api/v1/pending-actions/current?${p.toString()}`);
  },
};
