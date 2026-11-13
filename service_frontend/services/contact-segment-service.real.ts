/**
 * Real contact-segment service (plan 26 S4) - `GET/POST/PATCH/DELETE
 * /omnichannel/workspaces/{ws_id}/contact-segments[/{id}]` against
 * `lib/api-client`. Bound as the live `contactSegmentService` implementation
 * since S4 (see `contact-segment-service.ts`).
 */
import { apiFetch } from '@/lib/api-client';
import type { ContactSegment, CreateContactSegmentInput, UpdateContactSegmentInput } from '@/types/omnichannel';
import type { ContactSegmentService } from './contact-segment-service';

export const realContactSegmentService: ContactSegmentService = {
  list(workspaceId) {
    return apiFetch<ContactSegment[]>(`/omnichannel/workspaces/${workspaceId}/contact-segments`);
  },

  create(workspaceId, input: CreateContactSegmentInput) {
    return apiFetch<ContactSegment>(`/omnichannel/workspaces/${workspaceId}/contact-segments`, {
      method: 'POST',
      body: JSON.stringify(input),
    });
  },

  update(workspaceId, segmentId, input: UpdateContactSegmentInput) {
    return apiFetch<ContactSegment>(
      `/omnichannel/workspaces/${workspaceId}/contact-segments/${segmentId}`,
      { method: 'PATCH', body: JSON.stringify(input) },
    );
  },

  async remove(workspaceId, segmentId) {
    await apiFetch<void>(`/omnichannel/workspaces/${workspaceId}/contact-segments/${segmentId}`, {
      method: 'DELETE',
    });
  },
};
