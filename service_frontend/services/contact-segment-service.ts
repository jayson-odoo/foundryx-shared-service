/**
 * Contact-segment service (plan 26 - omnichannel Contacts module, roadmap A2).
 * UI -> hook -> service -> lib/api-client. S0 binds the MOCK implementation;
 * S1 lands the backend routes below and S4 swaps the export const to the real
 * api-client impl in ONE line. The interface IS the backend contract (§5.1):
 *
 *   GET    /omnichannel/workspaces/{wsId}/contact-segments
 *   POST   /omnichannel/workspaces/{wsId}/contact-segments   { name, description?, filter }
 *   PATCH  /omnichannel/workspaces/{wsId}/contact-segments/{id}
 *   DELETE /omnichannel/workspaces/{wsId}/contact-segments/{id}
 *
 * A segment stores the EXACT `FilterGroup` shape the Resource shell's filter
 * builder emits (D-A2-3) - `name` is unique per workspace case-insensitively,
 * capped at 100/workspace, and the stored tree is validated (save time) the
 * same way the list query validates it.
 */
import type { ContactSegment, CreateContactSegmentInput, UpdateContactSegmentInput } from '@/types/omnichannel';
import { mockContactSegmentService } from './contact-segment-service.mock';

export interface ContactSegmentService {
  list(workspaceId: string): Promise<ContactSegment[]>;
  create(workspaceId: string, input: CreateContactSegmentInput): Promise<ContactSegment>;
  update(workspaceId: string, segmentId: string, input: UpdateContactSegmentInput): Promise<ContactSegment>;
  remove(workspaceId: string, segmentId: string): Promise<void>;
}

// S0 MOCK - swap to real in S4 (plan 26); `contact-segment-service.real.ts`
// lands with the S1 backend routes above.
export const contactSegmentService: ContactSegmentService = mockContactSegmentService;
