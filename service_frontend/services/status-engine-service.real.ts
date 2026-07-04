/**
 * Real status-engine service — talks to FastAPI via the shared api-client.
 * Endpoints follow sprint-2/01 §backend.
 */
import { apiFetch } from '@/lib/api-client';
import type {
  CreateStatusInput,
  CreateTransitionInput,
  SimulateResult,
  StatusEntity,
  StatusGraph,
  StatusNodeData,
  StatusTransition,
  UpdateStatusInput,
  UpdateTransitionInput,
} from '@/types/status-engine';
import type { StatusEngineService } from './status-engine-service';

export const realStatusEngineService: StatusEngineService = {
  entities() {
    return apiFetch<{ data: StatusEntity[] }>('/status-entities').then((r) => r.data);
  },
  graph(entityType, scopeId) {
    const params = new URLSearchParams({ entityType });
    if (scopeId) params.set('scopeId', scopeId);
    return apiFetch<StatusGraph>(`/statuses?${params.toString()}`);
  },
  createStatus(input: CreateStatusInput) {
    return apiFetch<StatusNodeData>('/statuses', {
      method: 'POST',
      body: JSON.stringify(input),
    });
  },
  updateStatus(id, input: UpdateStatusInput) {
    return apiFetch<StatusNodeData>(`/statuses/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(input),
    });
  },
  async deleteStatus(id) {
    await apiFetch<void>(`/statuses/${id}`, { method: 'DELETE' });
  },
  setStatusActive(id, active) {
    return apiFetch<StatusNodeData>(`/statuses/${id}/${active ? 'activate' : 'deactivate'}`, {
      method: 'POST',
    });
  },
  migrateRecords(id, toStatusId) {
    return apiFetch<{ migrated: number }>(`/statuses/${id}/migrate-records`, {
      method: 'POST',
      body: JSON.stringify({ toStatusId }),
    });
  },
  reorder(entityType, orderedIds) {
    return apiFetch<StatusGraph>('/statuses/reorder', {
      method: 'POST',
      body: JSON.stringify({ entityType, orderedIds }),
    });
  },
  createTransition(input: CreateTransitionInput) {
    return apiFetch<StatusTransition>('/statuses/transitions', {
      method: 'POST',
      body: JSON.stringify(input),
    });
  },
  updateTransition(id, input: UpdateTransitionInput) {
    return apiFetch<StatusTransition>(`/statuses/transitions/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(input),
    });
  },
  async deleteTransition(id) {
    await apiFetch<void>(`/statuses/transitions/${id}`, { method: 'DELETE' });
  },
  simulate(entityType, asOf, apply) {
    return apiFetch<SimulateResult>(
      `/status-entities/${entityType}/simulate`,
      { method: 'POST', body: JSON.stringify({ asOf, apply }) },
    );
  },
};
