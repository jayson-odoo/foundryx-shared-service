/**
 * Real close-reason service (plan 27 S4) - written now against the §5.1
 * contract so the S0->S4 swap is the one-line binding in
 * `close-reason-service.ts`. Not yet wired (the backend routes land in S2).
 */
import { apiFetch } from '@/lib/api-client';
import type { CloseReason, CreateCloseReasonInput, UpdateCloseReasonInput } from '@/types/omnichannel';
import type { CloseReasonService } from './close-reason-service';

export const realCloseReasonService: CloseReasonService = {
  async list(workspaceId) {
    return apiFetch<CloseReason[]>(`/omnichannel/workspaces/${workspaceId}/close-reasons`);
  },

  async create(workspaceId, input: CreateCloseReasonInput) {
    return apiFetch<CloseReason>(`/omnichannel/workspaces/${workspaceId}/close-reasons`, {
      method: 'POST',
      body: JSON.stringify(input),
    });
  },

  async update(workspaceId, id, input: UpdateCloseReasonInput) {
    return apiFetch<CloseReason>(`/omnichannel/workspaces/${workspaceId}/close-reasons/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(input),
    });
  },

  async remove(workspaceId, id) {
    await apiFetch<void>(`/omnichannel/workspaces/${workspaceId}/close-reasons/${id}`, {
      method: 'DELETE',
    });
  },
};
