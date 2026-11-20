/**
 * Real broadcast service (plan 29 S4) - `GET/POST/PATCH/DELETE
 * /omnichannel/workspaces/{wsId}/broadcasts[/...]` against `lib/api-client`.
 * Bound as the live `broadcastService` implementation since S4 (see
 * `broadcast-service.ts`). §5.1 of the plan is the wire contract; the ONE
 * deviation the backend actually shipped (S1 report) is `audiencePreview`
 * being a POST with the full `BroadcastAudience` body, not a GET query
 * string - matches this file's `audiencePreview` below.
 */
import { apiFetch } from '@/lib/api-client';
import type {
  Broadcast,
  BroadcastAudience,
  BroadcastRecipient,
  CreateBroadcastInput,
  UpdateBroadcastInput,
} from '@/types/omnichannel';
import type { ListQuery, ListResult } from '@/types/resource';
import type { BroadcastService, RecipientQuery } from './broadcast-service';

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
  if (query.segment && query.segment !== 'all') p.set('segment', query.segment);
  return p;
}

function recipientParams(query: RecipientQuery): URLSearchParams {
  const p = new URLSearchParams();
  p.set('page', String(query.page));
  p.set('pageSize', String(query.pageSize));
  if (query.state) p.set('state', query.state);
  if (query.search) p.set('search', query.search);
  return p;
}

export const realBroadcastService: BroadcastService = {
  list(workspaceId, query) {
    return apiFetch<ListResult<Broadcast>>(
      `/omnichannel/workspaces/${workspaceId}/broadcasts?${listParams(query).toString()}`,
    );
  },

  get(workspaceId, id) {
    return apiFetch<Broadcast>(`/omnichannel/workspaces/${workspaceId}/broadcasts/${id}`);
  },

  audiencePreview(workspaceId, audience: BroadcastAudience) {
    return apiFetch<{ count: number }>(
      `/omnichannel/workspaces/${workspaceId}/broadcasts/audience-preview`,
      { method: 'POST', body: JSON.stringify({ audience }) },
    );
  },

  create(workspaceId, input: CreateBroadcastInput) {
    return apiFetch<Broadcast>(`/omnichannel/workspaces/${workspaceId}/broadcasts`, {
      method: 'POST',
      body: JSON.stringify(input),
    });
  },

  update(workspaceId, id, input: UpdateBroadcastInput) {
    return apiFetch<Broadcast>(`/omnichannel/workspaces/${workspaceId}/broadcasts/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(input),
    });
  },

  async remove(workspaceId, id) {
    await apiFetch<void>(`/omnichannel/workspaces/${workspaceId}/broadcasts/${id}`, {
      method: 'DELETE',
    });
  },

  duplicate(workspaceId, id) {
    return apiFetch<Broadcast>(`/omnichannel/workspaces/${workspaceId}/broadcasts/${id}/duplicate`, {
      method: 'POST',
    });
  },

  send(workspaceId, id, scheduledAt) {
    return apiFetch<Broadcast>(`/omnichannel/workspaces/${workspaceId}/broadcasts/${id}/send`, {
      method: 'POST',
      body: JSON.stringify({ scheduledAt: scheduledAt ?? null }),
    });
  },

  cancel(workspaceId, id) {
    return apiFetch<Broadcast>(`/omnichannel/workspaces/${workspaceId}/broadcasts/${id}/cancel`, {
      method: 'POST',
    });
  },

  testSend(workspaceId, id, contactId) {
    return apiFetch<{ messageId: string }>(
      `/omnichannel/workspaces/${workspaceId}/broadcasts/${id}/test-send`,
      { method: 'POST', body: JSON.stringify({ contactId }) },
    );
  },

  recipients(workspaceId, id, query) {
    return apiFetch<ListResult<BroadcastRecipient>>(
      `/omnichannel/workspaces/${workspaceId}/broadcasts/${id}/recipients?${recipientParams(query).toString()}`,
    );
  },
};
