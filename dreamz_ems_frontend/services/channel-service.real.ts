/**
 * Real channel service — talks to FastAPI via the shared api-client. Wired in
 * Phase B. Endpoints follow plan 04 §6.
 */
import { apiFetch, apiFetchText } from '@/lib/api-client';
import type {
  Channel,
  ChannelProfile,
  UpdateChannelInput,
  UpdateChannelProfileInput,
} from '@/types/omnichannel';
import type { ListQuery, ListResult } from '@/types/resource';
import type { ChannelService, TestConnectionResult } from './channel-service';

function listParams(query: ListQuery): URLSearchParams {
  const p = new URLSearchParams();
  p.set('page', String(query.page));
  p.set('page_size', String(query.pageSize));
  if (query.search) p.set('search', query.search);
  if (query.sort) {
    p.set('sort_by', query.sort.id);
    p.set('sort_dir', query.sort.desc ? 'desc' : 'asc');
  }
  if (query.statusView) p.set('status_view', query.statusView);
  if (query.filter) p.set('filter', JSON.stringify(query.filter));
  return p;
}

export const realChannelService: ChannelService = {
  list(query) {
    return apiFetch<ListResult<Channel>>(`/omnichannel/channels?${listParams(query).toString()}`);
  },
  get(id) {
    return apiFetch<Channel>(`/omnichannel/channels/${id}`);
  },
  getAt(query, index) {
    const p = listParams(query);
    p.set('index', String(index));
    return apiFetch<{ channel: Channel | null; total: number }>(
      `/omnichannel/channels/at?${p.toString()}`,
    );
  },
  listByWorkspace(workspaceId) {
    return apiFetch<Channel[]>(`/omnichannel/channels/by-workspace/${workspaceId}`);
  },
  update(id, input: UpdateChannelInput) {
    return apiFetch<Channel>(`/omnichannel/channels/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(input),
    });
  },
  testConnection(id) {
    return apiFetch<TestConnectionResult>(`/omnichannel/channels/${id}/test`, { method: 'POST' });
  },
  syncConfig(id) {
    return apiFetch<Channel>(`/omnichannel/channels/${id}/sync-config`, { method: 'POST' });
  },
  getProfile(id) {
    return apiFetch<ChannelProfile>(`/omnichannel/channels/${id}/profile`);
  },
  syncProfile(id) {
    return apiFetch<ChannelProfile>(`/omnichannel/channels/${id}/profile/sync`, { method: 'POST' });
  },
  saveProfile(id, input: UpdateChannelProfileInput) {
    return apiFetch<ChannelProfile>(`/omnichannel/channels/${id}/profile`, {
      method: 'PATCH',
      body: JSON.stringify(input),
    });
  },
  async disconnect(ids) {
    await apiFetch<void>('/omnichannel/channels/disconnect', {
      method: 'POST',
      body: JSON.stringify({ ids }),
    });
  },
  async restore(ids) {
    await apiFetch<void>('/omnichannel/channels/restore', {
      method: 'POST',
      body: JSON.stringify({ ids }),
    });
  },
  async remove(ids) {
    await apiFetch<void>('/omnichannel/channels/delete', {
      method: 'POST',
      body: JSON.stringify({ ids }),
    });
  },
  exportCsv(query, columns, ids) {
    return apiFetchText('/omnichannel/channels/export', {
      method: 'POST',
      body: JSON.stringify({
        columns,
        ids,
        search: query.search,
        sortBy: query.sort?.id,
        sortDir: query.sort ? (query.sort.desc ? 'desc' : 'asc') : undefined,
        statusView: query.statusView ?? 'active',
        filter: query.filter,
      }),
    });
  },
};
