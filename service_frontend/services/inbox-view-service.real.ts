/**
 * Real inbox-view service (plan 27 S4) - written now against the §5.1
 * contract so the S0->S4 swap is the one-line binding in
 * `inbox-view-service.ts`. Not yet wired (the backend routes land in S2).
 */
import { apiFetch } from '@/lib/api-client';
import type { CreateInboxViewInput, InboxView, UpdateInboxViewInput } from '@/types/omnichannel';
import type { InboxViewService } from './inbox-view-service';

export const realInboxViewService: InboxViewService = {
  async list(workspaceId) {
    return apiFetch<InboxView[]>(`/omnichannel/workspaces/${workspaceId}/inbox-views`);
  },

  async create(workspaceId, input: CreateInboxViewInput) {
    return apiFetch<InboxView>(`/omnichannel/workspaces/${workspaceId}/inbox-views`, {
      method: 'POST',
      body: JSON.stringify(input),
    });
  },

  async update(workspaceId, id, input: UpdateInboxViewInput) {
    return apiFetch<InboxView>(`/omnichannel/workspaces/${workspaceId}/inbox-views/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(input),
    });
  },

  async remove(workspaceId, id) {
    await apiFetch<void>(`/omnichannel/workspaces/${workspaceId}/inbox-views/${id}`, {
      method: 'DELETE',
    });
  },
};
