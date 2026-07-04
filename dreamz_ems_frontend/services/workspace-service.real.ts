/**
 * Real workspace service — talks to FastAPI via the shared api-client. Wired in
 * Phase B (the mock is bound until then). Endpoints follow plan 04 §6.
 */
import { apiFetch, apiFetchText } from '@/lib/api-client';
import type {
  CreateWorkspaceInput,
  MemberCandidate,
  UpdateWorkspaceInput,
  Workspace,
  WorkspaceMember,
} from '@/types/omnichannel';
import type { ListQuery, ListResult } from '@/types/resource';
import type { WorkspaceService } from './workspace-service';

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

export const realWorkspaceService: WorkspaceService = {
  list(query) {
    return apiFetch<ListResult<Workspace>>(`/omnichannel/workspaces?${listParams(query).toString()}`);
  },
  get(id) {
    return apiFetch<Workspace>(`/omnichannel/workspaces/${id}`);
  },
  getAt(query, index) {
    const p = listParams(query);
    p.set('index', String(index));
    return apiFetch<{ workspace: Workspace | null; total: number }>(
      `/omnichannel/workspaces/at?${p.toString()}`,
    );
  },
  create(input: CreateWorkspaceInput) {
    return apiFetch<Workspace>('/omnichannel/workspaces', {
      method: 'POST',
      body: JSON.stringify(input),
    });
  },
  update(id, input: UpdateWorkspaceInput) {
    return apiFetch<Workspace>(`/omnichannel/workspaces/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(input),
    });
  },
  async trash(ids) {
    await apiFetch<void>('/omnichannel/workspaces/trash', {
      method: 'POST',
      body: JSON.stringify({ ids }),
    });
  },
  async restore(ids) {
    await apiFetch<void>('/omnichannel/workspaces/restore', {
      method: 'POST',
      body: JSON.stringify({ ids }),
    });
  },
  getMembers(workspaceId, search) {
    const p = new URLSearchParams();
    if (search) p.set('search', search);
    const qs = p.toString();
    return apiFetch<WorkspaceMember[]>(
      `/omnichannel/workspaces/${workspaceId}/members${qs ? `?${qs}` : ''}`,
    );
  },
  listAssignable(workspaceId, search) {
    const p = new URLSearchParams();
    if (search) p.set('search', search);
    const qs = p.toString();
    return apiFetch<MemberCandidate[]>(
      `/omnichannel/workspaces/${workspaceId}/assignable${qs ? `?${qs}` : ''}`,
    );
  },
  async assignMembers(workspaceId, userIds) {
    await apiFetch<void>(`/omnichannel/workspaces/${workspaceId}/members`, {
      method: 'POST',
      body: JSON.stringify({ userIds }),
    });
  },
  async removeMember(workspaceId, userId) {
    await apiFetch<void>(`/omnichannel/workspaces/${workspaceId}/members/${userId}`, {
      method: 'DELETE',
    });
  },
  exportCsv(query, columns, ids) {
    return apiFetchText('/omnichannel/workspaces/export', {
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
