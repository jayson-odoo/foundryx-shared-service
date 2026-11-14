/**
 * Real team service (plan 28 S5) - talks to the core `/teams` routes
 * (`app/api/v1/teams.py`, S1). List/record-nav params are SNAKE_CASE like
 * Users/Workspaces (`page`, `page_size`, `search`, `sort_by`, `sort_dir`) -
 * the wire ALIGNS with those two here even though the plan's §5.1 sketch used
 * `q`/`sort`/`pageSize` shorthand; the router itself is the source of truth
 * (`GET /teams` declares `page`/`page_size`/`search`/`sort_by`/`sort_dir`).
 *
 * `sort.id` on the Teams list config uses the SHELL's short column ids
 * (`name`, `status`, `created`) - `created` maps to the backend's `createdAt`
 * sort key; `status` has no backend sort column (`_SORT_COLUMNS` only knows
 * `name`/`sortOrder`/`createdAt`) so it is sent as-is and the backend falls
 * back to its default `sortOrder` ordering rather than erroring (no 422 on
 * an unknown `sort_by` - see `team_repository.list`).
 */
import { apiFetch } from '@/lib/api-client';
import type { ListQuery, ListResult } from '@/types/resource';
import type { CreateTeamInput, MyTeam, Team, UpdateTeamInput } from '@/types/team';
import type { TeamService } from './team-service';

const SORT_ID_MAP: Record<string, string> = {
  created: 'createdAt',
};

function listParams(query: ListQuery): URLSearchParams {
  const p = new URLSearchParams();
  p.set('page', String(query.page));
  p.set('page_size', String(query.pageSize));
  if (query.search) p.set('search', query.search);
  if (query.sort) {
    p.set('sort_by', SORT_ID_MAP[query.sort.id] ?? query.sort.id);
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
    p.set('sort_by', SORT_ID_MAP[query.sort.id] ?? query.sort.id);
    p.set('sort_dir', query.sort.desc ? 'desc' : 'asc');
  }
  if (query.filter) p.set('filter', JSON.stringify(query.filter));
  return p;
}

export const realTeamService: TeamService = {
  list(query) {
    return apiFetch<ListResult<Team>>(`/teams?${listParams(query).toString()}`);
  },
  get(id) {
    return apiFetch<Team>(`/teams/${id}`);
  },
  getAt(query, index) {
    return apiFetch<{ team: Team | null; total: number }>(
      `/teams/at?${navParams(query, index).toString()}`,
    );
  },
  mine() {
    return apiFetch<MyTeam[]>('/teams/mine');
  },
  create(input: CreateTeamInput) {
    return apiFetch<Team>('/teams', { method: 'POST', body: JSON.stringify(input) });
  },
  update(id, input: UpdateTeamInput) {
    return apiFetch<Team>(`/teams/${id}`, { method: 'PATCH', body: JSON.stringify(input) });
  },
  async remove(id) {
    await apiFetch<void>(`/teams/${id}`, { method: 'DELETE' });
  },
};
