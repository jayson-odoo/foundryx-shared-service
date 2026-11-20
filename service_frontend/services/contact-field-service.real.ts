/**
 * Real contact-field registry service (plan 25) - `GET/POST/PATCH/DELETE
 * /omnichannel/workspaces/{workspaceId}/contact-fields[/{fieldId}]` against
 * `lib/api-client`. Bound as the live `contactFieldService` implementation
 * since S4 (see `contact-field-service.ts`).
 */
import { apiFetch } from '@/lib/api-client';
import type {
  ContactField,
  CreateContactFieldInput,
  UpdateContactFieldInput,
} from '@/types/omnichannel';
import type { ContactFieldService } from './contact-field-service';

export const realContactFieldService: ContactFieldService = {
  async list(workspaceId) {
    return apiFetch<ContactField[]>(`/omnichannel/workspaces/${workspaceId}/contact-fields`);
  },

  async create(workspaceId, input: CreateContactFieldInput) {
    return apiFetch<ContactField>(`/omnichannel/workspaces/${workspaceId}/contact-fields`, {
      method: 'POST',
      body: JSON.stringify(input),
    });
  },

  async update(workspaceId, fieldId, input: UpdateContactFieldInput) {
    return apiFetch<ContactField>(
      `/omnichannel/workspaces/${workspaceId}/contact-fields/${fieldId}`,
      { method: 'PATCH', body: JSON.stringify(input) },
    );
  },

  async remove(workspaceId, fieldId) {
    await apiFetch<void>(`/omnichannel/workspaces/${workspaceId}/contact-fields/${fieldId}`, {
      method: 'DELETE',
    });
  },
};
