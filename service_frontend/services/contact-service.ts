/**
 * Contact-list service (plan 26 - omnichannel Contacts module, roadmap A2).
 * UI -> hook -> service -> lib/api-client. S0 binds the MOCK implementation
 * (S1-S3 land the backend routes below, S4 swaps the export const to the
 * real api-client impl in ONE line - see bottom).
 *
 * The interface IS the backend contract (plan §5.1):
 *
 *   GET    /omnichannel/workspaces/{wsId}/contacts
 *            ?page=&pageSize=&search=&sortBy=&sortDir=&filter=<json>&segment=<id>
 *            -> { data, total, page }
 *   POST   /omnichannel/workspaces/{wsId}/contacts                     -> 201
 *   POST   /omnichannel/workspaces/{wsId}/contacts/bulk/assign         -> BulkResult
 *   POST   /omnichannel/workspaces/{wsId}/contacts/bulk/tags           -> BulkResult
 *   POST   /omnichannel/workspaces/{wsId}/contacts/bulk/lifecycle      -> BulkResult
 *   POST   /omnichannel/workspaces/{wsId}/contacts/export              -> { jobId }
 *   GET    /omnichannel/workspaces/{wsId}/contacts/export/{jobId}/file -> text/csv
 *
 * (unchanged, reused) GET/PATCH /omnichannel/contacts/{id} and the lifecycle /
 * fields / tags routes ride `conversation-service` / `contact-field-service` /
 * `contact-tag-service` exactly as the A1 Contact panel already does - this
 * service owns ONLY the list/create/bulk/export seams A2 adds.
 */
import type {
  BulkAssignInput,
  BulkLifecycleInput,
  BulkResult,
  BulkTagsInput,
  ContactExportRequest,
  ContactListItem,
  CreateContactInput,
} from '@/types/omnichannel';
import type { ListQuery, ListResult } from '@/types/resource';
import { realContactService } from './contact-service.real';

export interface ContactService {
  /** Workspace-scoped, server search/sort/filter/segment/paginate (D-A2-12 -
   *  a NEW endpoint, distinct from the inbox thread list). */
  list(workspaceId: string, query: ListQuery): Promise<ListResult<ContactListItem>>;
  /** Record-nav: the contact at `index` within the ordered query, plus total. */
  getAt(
    workspaceId: string,
    query: ListQuery,
    index: number,
  ): Promise<{ contact: ContactListItem | null; total: number }>;
  get(workspaceId: string, contactId: string): Promise<ContactListItem>;
  /** Create (D-A2-4) - phone required, gets the workspace's initial lifecycle
   *  stage when `lifecycleStatusId` is omitted. 422 `fieldErrors` on failure. */
  create(workspaceId: string, input: CreateContactInput): Promise<ContactListItem>;
  /** Bulk actions (D-A2-5) - each id resolved tenant+workspace scoped, ids
   *  capped at 500 (enforced server-side; the UI never sends more). */
  bulkAssign(workspaceId: string, input: BulkAssignInput): Promise<BulkResult>;
  bulkTags(workspaceId: string, input: BulkTagsInput): Promise<BulkResult>;
  bulkLifecycle(workspaceId: string, input: BulkLifecycleInput): Promise<BulkResult>;
  /**
   * Export (D-A2-6a) - creates a `background_jobs` row, polls briefly, then
   * resolves the CSV text of the finished job. Throws
   * `ExportPendingError` (see `lib/service-errors.ts`) when the job hasn't
   * finished inside the wait window - the caller points the user at Jobs
   * rather than showing a bare failure ("never a silent failure").
   */
  exportContacts(workspaceId: string, req: ContactExportRequest): Promise<string>;
}

// Real backend (plan 26 S4) - routes landed S1 (list + segments) / S2
// (create + bulk) / S3 (import + export).
export const contactService: ContactService = realContactService;
