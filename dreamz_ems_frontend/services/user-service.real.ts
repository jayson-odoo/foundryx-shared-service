/**
 * Real user service — talks to FastAPI via the shared api-client. The backend
 * already returns camelCase matching the `User` type, so no field remapping.
 */
import { apiFetch, apiFetchText } from '@/lib/api-client';
import type { CreateUserInput, UpdateUserInput, User } from '@/types/user';
import type { ListQuery, ListResult } from '@/types/resource';
import type { UserService } from './user-service';

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

function navParams(query: ListQuery, index: number): URLSearchParams {
  const p = new URLSearchParams();
  p.set('index', String(index));
  if (query.search) p.set('search', query.search);
  if (query.sort) {
    p.set('sort_by', query.sort.id);
    p.set('sort_dir', query.sort.desc ? 'desc' : 'asc');
  }
  if (query.statusView) p.set('status_view', query.statusView);
  if (query.filter) p.set('filter', JSON.stringify(query.filter));
  return p;
}

export const realUserService: UserService = {
  list(query) {
    return apiFetch<ListResult<User>>(`/users?${listParams(query).toString()}`);
  },
  get(id) {
    return apiFetch<User>(`/users/${id}`);
  },
  getAt(query, index) {
    return apiFetch<{ user: User | null; total: number }>(
      `/users/at?${navParams(query, index).toString()}`,
    );
  },
  create(input: CreateUserInput) {
    return apiFetch<User>('/users', { method: 'POST', body: JSON.stringify(input) });
  },
  update(id, input: UpdateUserInput) {
    return apiFetch<User>(`/users/${id}`, { method: 'PATCH', body: JSON.stringify(input) });
  },
  async trash(ids) {
    await apiFetch<void>('/users/trash', { method: 'POST', body: JSON.stringify({ ids }) });
  },
  async restore(ids) {
    await apiFetch<void>('/users/restore', { method: 'POST', body: JSON.stringify({ ids }) });
  },
  async invite(ids) {
    await apiFetch<{ sent: number }>('/users/invite', {
      method: 'POST',
      body: JSON.stringify({ ids }),
    });
  },
  async resetPassword(id) {
    await apiFetch<void>(`/users/${id}/reset-password`, { method: 'POST' });
  },
  async resendVerification(id) {
    await apiFetch<void>(`/users/${id}/resend-verification`, { method: 'POST' });
  },
  exportCsv(query, columns, ids) {
    return apiFetchText('/users/export', {
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
