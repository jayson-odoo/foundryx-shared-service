/**
 * Contact-tag service (plan 25 - omnichannel contact data model). UI -> hook ->
 * service -> lib/api-client. Phase A (S0) binds the MOCK implementation; Phase
 * B (S4) swaps `contactTagService` to the real api-client impl in ONE line
 * (see bottom). The interface IS the backend contract (plan §5.1):
 *
 *   GET    /omnichannel/workspaces/{id}/contact-tags
 *   POST   /omnichannel/workspaces/{id}/contact-tags
 *   PATCH  /omnichannel/workspaces/{id}/contact-tags/{tagId}
 *   DELETE /omnichannel/workspaces/{id}/contact-tags/{tagId}
 *
 * `name` is unique per workspace case-insensitively; delete removes the tag's
 * links but leaves contacts otherwise unchanged (AC-CDM-09/11).
 */
import type { ContactTag, CreateContactTagInput, UpdateContactTagInput } from '@/types/omnichannel';
import { realContactTagService } from './contact-tag-service.real';

export interface ContactTagService {
  list(workspaceId: string): Promise<ContactTag[]>;
  create(workspaceId: string, input: CreateContactTagInput): Promise<ContactTag>;
  update(workspaceId: string, tagId: string, input: UpdateContactTagInput): Promise<ContactTag>;
  remove(workspaceId: string, tagId: string): Promise<void>;
}

// Real backend (plan 25 S4) - routes landed in S1.
export const contactTagService: ContactTagService = realContactTagService;
