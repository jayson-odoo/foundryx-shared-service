/**
 * Real contact-tag service (plan 25) - `GET/POST/PATCH/DELETE
 * /omnichannel/workspaces/{workspaceId}/contact-tags[/{tagId}]` against
 * `lib/api-client`. Bound as the live `contactTagService` implementation
 * since S4 (see `contact-tag-service.ts`).
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
