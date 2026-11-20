/**
 * Contact-field registry service (plan 25 - omnichannel contact data model).
 * UI -> hook -> service -> lib/api-client. Phase A (S0) binds the MOCK
 * implementation; Phase B (S4) swaps `contactFieldService` to the real
 * api-client impl in ONE line (see bottom). The interface IS the backend
 * contract (plan §5.1):
 *
 *   GET    /omnichannel/workspaces/{id}/contact-fields
 *   POST   /omnichannel/workspaces/{id}/contact-fields
 *   PATCH  /omnichannel/workspaces/{id}/contact-fields/{fieldId}
 *   DELETE /omnichannel/workspaces/{id}/contact-fields/{fieldId}
 *
 * `key` + `type` are immutable after create (D6) - `UpdateContactFieldInput`
 * deliberately has no `key`/`type`. Delete strips the key from every contact's
 * `customFields` in that workspace (AC-CDM-04).
 */
import type {
  ContactField,
  CreateContactFieldInput,
  UpdateContactFieldInput,
} from '@/types/omnichannel';
import { realContactFieldService } from './contact-field-service.real';

export interface ContactFieldService {
  list(workspaceId: string): Promise<ContactField[]>;
  create(workspaceId: string, input: CreateContactFieldInput): Promise<ContactField>;
  update(workspaceId: string, fieldId: string, input: UpdateContactFieldInput): Promise<ContactField>;
  remove(workspaceId: string, fieldId: string): Promise<void>;
}

// Real backend (plan 25 S4) - routes landed in S1.
export const contactFieldService: ContactFieldService = realContactFieldService;
