/**
 * Real role service (Phase B) — talks to FastAPI via the shared api-client.
 * Backend returns camelCase matching the role types, so no field remapping.
 * Bound in one line from role-service.ts when the backend lands.
 */
import { apiFetch, apiFetchText } from '@/lib/api-client';
import type {
  AssignableUser,
  CreateRoleInput,
  RoleDetail,
  RoleListItem,
  RoleUser,
  UpdateRoleInput,
} from '@/types/role';
import type { ListQuery, ListResult } from '@/types/resource';
import type { RoleService } from './role-service';

function listParams(query: ListQuery): URLSearchParams {
  const p = new URLSearchParams();
  p.set('page', String(query.page));
  p.set('page_size', String(query.pageSize));
  if (query.search) p.set('search', query.search);
  if (query.sort) {
    p.set('sort_by', query.sort.id);
    p.set('sort_dir', query.sort.desc ? 'desc' : 'asc');
  }
  if (query.filter) p.set('filter', JSON.stringify(query.filter));
  return p;
}

function navParams(query: ListQuery, index: number): URLSearchParams {
  const p = new URLSearchParams();
  p.set('index', String(index));
  if (query.search) p.set('search', query.search);
  if (query.sort) {
    p.set('sort_by', query.sort.id);
    p.set('sort_dir', query.sort.desc ? 'desc' : 'asc');
  }
  if (query.filter) p.set('filter', JSON.stringify(query.filter));
  return p;
}

export const realRoleService: RoleService = {
  list(query) {
    return apiFetch<ListResult<RoleListItem>>(`/roles?${listParams(query).toString()}`);
  },
  get(id) {
    return apiFetch<RoleDetail>(`/roles/${id}`);
  },
  getAt(query, index) {
    return apiFetch<{ role: RoleDetail | null; total: number }>(
      `/roles/at?${navParams(query, index).toString()}`,
    );
  },
  create(input: CreateRoleInput) {
    return apiFetch<RoleDetail>('/roles', { method: 'POST', body: JSON.stringify(input) });
  },
  update(id, input: UpdateRoleInput) {
    return apiFetch<RoleDetail>(`/roles/${id}`, { method: 'PATCH', body: JSON.stringify(input) });
  },
  async remove(id) {
    await apiFetch<void>(`/roles/${id}`, { method: 'DELETE' });
  },
  getAssignedUsers(roleId, search) {
    const p = new URLSearchParams();
    if (search) p.set('search', search);
    const qs = p.toString();
    return apiFetch<RoleUser[]>(`/roles/${roleId}/users${qs ? `?${qs}` : ''}`);
  },
  listAssignable(roleId, search) {
    const p = new URLSearchParams();
    if (search) p.set('search', search);
    const qs = p.toString();
    return apiFetch<AssignableUser[]>(`/roles/${roleId}/assignable${qs ? `?${qs}` : ''}`);
  },
  async assignUsers(roleId, userIds) {
    await apiFetch<void>(`/roles/${roleId}/users`, {
      method: 'POST',
      body: JSON.stringify({ userIds }),
    });
  },
  async removeUser(roleId, userId) {
    await apiFetch<void>(`/roles/${roleId}/users/${userId}`, { method: 'DELETE' });
  },
  exportCsv(query, columns, ids) {
    return apiFetchText('/roles/export', {
      method: 'POST',
      body: JSON.stringify({
        columns,
        ids,
        search: query.search,
        sortBy: query.sort?.id,
        sortDir: query.sort ? (query.sort.desc ? 'desc' : 'asc') : undefined,
        filter: query.filter,
      }),
    });
  },
};
