/**
 * Real contact-list service (plan 26 S4 - swaps the S0 mock). Talks to the
 * S1-S3 backend routes documented on `contact-service.ts`'s `ContactService`
 * interface. Two deliberate reconciliations vs the mock:
 *
 * - The shell's segment `SearchSelect` always carries a value, defaulting to
 *   the `ALL_CONTACTS_SEGMENT_ID` sentinel (`'all'`, see `./components/
 *   segment-picker.ts`) - the backend has no segment named "all" and 404s
 *   `SegmentNotFound` for any unrecognized id, so every query/export param
 *   builder here drops the sentinel to `undefined` before it reaches the
 *   wire (`realSegment`).
 * - There is no dedicated "record at index" endpoint for contacts (unlike
 *   `/roles/at`) - `getAt` re-issues `list()` with the SAME query, computing
 *   the page that contains `index` (the backend caps `pageSize` at 200, the
 *   `Math.min` guard mirrors that).
 */
import { apiFetch, apiFetchBlob, ApiError } from '@/lib/api-client';
import { ExportPendingError } from '@/lib/service-errors';
import type { Job } from '@/types/jobs';
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
import type { ContactService } from './contact-service';

const MAX_PAGE_SIZE = 200; // backend `pageSize: Query(..., le=200)`

// Mirrors `ALL_CONTACTS_SEGMENT_ID` in `app/(protected)/omnichannel/contacts/
// components/segment-picker.ts` (a service must not import from `app/` -
// layering runs UI -> hook -> service, never back) - the shell's segment
// `SearchSelect` always carries a value, defaulting to this sentinel; the
// backend has no segment named "all" and 404s `SegmentNotFound` for any
// unrecognized id.
const ALL_SEGMENT_SENTINEL = 'all';

function realSegment(segment: string | null | undefined): string | undefined {
  return segment && segment !== ALL_SEGMENT_SENTINEL ? segment : undefined;
}

function listParams(query: ListQuery): URLSearchParams {
  const p = new URLSearchParams();
  p.set('page', String(query.page));
  p.set('pageSize', String(query.pageSize));
  if (query.search) p.set('search', query.search);
  if (query.sort) {
    p.set('sortBy', query.sort.id);
    p.set('sortDir', query.sort.desc ? 'desc' : 'asc');
  }
  if (query.filter) p.set('filter', JSON.stringify(query.filter));
  const segment = realSegment(query.segment);
  if (segment) p.set('segment', segment);
  return p;
}

// ── export job wait window (D-A2-6a) ────────────────────────────────────────
const EXPORT_POLL_INTERVAL_MS = 400;
const EXPORT_WAIT_ATTEMPTS = 5; // ~2s before falling back to the Jobs surface

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForExportJob(jobId: string): Promise<Job> {
  for (let attempt = 0; attempt < EXPORT_WAIT_ATTEMPTS; attempt++) {
    const job = await apiFetch<Job>(`/jobs/${jobId}`);
    if (job.status === 'done' || job.status === 'failed' || job.status === 'aborted') return job;
    await wait(EXPORT_POLL_INTERVAL_MS);
  }
  throw new ExportPendingError('The export is still running - it will finish in Jobs.', jobId);
}

export const realContactService: ContactService = {
  list(workspaceId, query) {
    return apiFetch<ListResult<ContactListItem>>(
      `/omnichannel/workspaces/${workspaceId}/contacts?${listParams(query).toString()}`,
    );
  },

  async getAt(workspaceId, query, index) {
    const pageSize = Math.max(1, Math.min(query.pageSize || MAX_PAGE_SIZE, MAX_PAGE_SIZE));
    const page = Math.floor(index / pageSize);
    const within = index - page * pageSize;
    const res = await this.list(workspaceId, { ...query, page, pageSize });
    return { contact: res.data[within] ?? null, total: res.total };
  },

  async get(workspaceId, contactId) {
    // The single-record GET rides the existing A1 conversation route (no
    // second "fetch one contact" endpoint) - it returns `ThreadItem` without
    // `channels[]` (that field is a list/export-only decoration, S1 D-A2-11);
    // the detail page never reads `.channels` off this record, so an honest
    // empty array (never fabricated data) fills the type.
    const thread = await apiFetch<Omit<ContactListItem, 'channels'>>(`/omnichannel/contacts/${contactId}`);
    void workspaceId;
    return { ...thread, channels: [] };
  },

  create(workspaceId, input: CreateContactInput) {
    return apiFetch<ContactListItem>(`/omnichannel/workspaces/${workspaceId}/contacts`, {
      method: 'POST',
      body: JSON.stringify(input),
    });
  },

  bulkAssign(workspaceId, input: BulkAssignInput) {
    return apiFetch<BulkResult>(`/omnichannel/workspaces/${workspaceId}/contacts/bulk/assign`, {
      method: 'POST',
      body: JSON.stringify(input),
    });
  },

  bulkTags(workspaceId, input: BulkTagsInput) {
    return apiFetch<BulkResult>(`/omnichannel/workspaces/${workspaceId}/contacts/bulk/tags`, {
      method: 'POST',
      body: JSON.stringify(input),
    });
  },

  bulkLifecycle(workspaceId, input: BulkLifecycleInput) {
    return apiFetch<BulkResult>(`/omnichannel/workspaces/${workspaceId}/contacts/bulk/lifecycle`, {
      method: 'POST',
      body: JSON.stringify(input),
    });
  },

  async exportContacts(workspaceId, req: ContactExportRequest) {
    const body = {
      columns: req.columns,
      ids: req.ids,
      search: req.search,
      filter: req.filter ?? undefined,
      segment: realSegment(req.segment),
      sortBy: req.sortBy,
      sortDir: req.sortDir,
    };
    const { jobId } = await apiFetch<{ jobId: string }>(
      `/omnichannel/workspaces/${workspaceId}/contacts/export`,
      { method: 'POST', body: JSON.stringify(body) },
    );
    const job = await waitForExportJob(jobId);
    if (job.status === 'failed' || job.status === 'aborted') {
      throw new ApiError(job.error ?? 'The export could not be completed.', 500);
    }
    const blob = await apiFetchBlob(
      `/omnichannel/workspaces/${workspaceId}/contacts/export/${jobId}/file`,
    );
    return blob.text();
  },
};
