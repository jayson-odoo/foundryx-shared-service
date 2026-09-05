/**
 * Real contact-tag service (plan 25, S1 backend). Not yet bound (see
 * contact-tag-service.ts) - the routes land in S1; this implementation is
 * written against the plan §5.1 contract so the S4 swap is a one-line change
 * once the backend exists.
 */
import { apiFetch } from '@/lib/api-client';
import type { ContactTag, CreateContactTagInput, UpdateContactTagInput } from '@/types/omnichannel';
import type { ContactTagService } from './contact-tag-service';

export const realContactTagService: ContactTagService = {
  async list(workspaceId) {
    return apiFetch<ContactTag[]>(`/omnichannel/workspaces/${workspaceId}/contact-tags`);
  },

  async create(workspaceId, input: CreateContactTagInput) {
    return apiFetch<ContactTag>(`/omnichannel/workspaces/${workspaceId}/contact-tags`, {
      method: 'POST',
      body: JSON.stringify(input),
    });
  },

  async update(workspaceId, tagId, input: UpdateContactTagInput) {
    return apiFetch<ContactTag>(`/omnichannel/workspaces/${workspaceId}/contact-tags/${tagId}`, {
      method: 'PATCH',
      body: JSON.stringify(input),
    });
  },

  async remove(workspaceId, tagId) {
    await apiFetch<void>(`/omnichannel/workspaces/${workspaceId}/contact-tags/${tagId}`, {
      method: 'DELETE',
    });
  },
};
