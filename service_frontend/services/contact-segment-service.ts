/**
 * Contact-segment service - pulled forward from plan 26 (A2, roadmap) so the
 * Broadcasts audience picker (plan 29) has a segment data source. A2 has not
 * merged to this base yet; this file mirrors the `s26` worktree's
 * `contact-segment-service.ts` INTERFACE field-for-field (same method names,
 * same shapes) so A2's merge is a rebinding of this export, never a rewrite.
 *
 * S0 MOCK - swap to real in S4 (plan 29), once A2 lands its own
 * `contact-segment-service.real.ts` behind the SAME interface:
 *
 *   GET    /omnichannel/workspaces/{wsId}/contact-segments
 *   POST   /omnichannel/workspaces/{wsId}/contact-segments   { name, description?, filter }
 *   PATCH  /omnichannel/workspaces/{wsId}/contact-segments/{id}
 *   DELETE /omnichannel/workspaces/{wsId}/contact-segments/{id}
 */
import type { ContactSegment, CreateContactSegmentInput, UpdateContactSegmentInput } from '@/types/omnichannel';
import { mockContactSegmentService } from './contact-segment-service.mock';

export interface ContactSegmentService {
  list(workspaceId: string): Promise<ContactSegment[]>;
  create(workspaceId: string, input: CreateContactSegmentInput): Promise<ContactSegment>;
  update(workspaceId: string, segmentId: string, input: UpdateContactSegmentInput): Promise<ContactSegment>;
  remove(workspaceId: string, segmentId: string): Promise<void>;
}

// S0 MOCK - swap to real in S4 (plan 29); A2's `contact-segment-service.real.ts`
// lands with its own backend routes and this line rebinds to it.
export const contactSegmentService: ContactSegmentService = mockContactSegmentService;
