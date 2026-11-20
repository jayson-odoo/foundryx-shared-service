/**
 * Real team service (plan 28 S5) - list/record-nav params are SNAKE_CASE
 * (`page`/`page_size`/`search`/`sort_by`/`sort_dir`), matching the actual
 * router (`app/api/v1/teams.py`) rather than the plan's `q`/`sort`/`pageSize`
 * sketch; the `created` shell column id maps to the backend's `createdAt`
 * sort key.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Team } from '@/types/team';

const apiFetchMock = vi.fn();
vi.mock('@/lib/api-client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api-client')>();
  return { ...actual, apiFetch: (...args: Parameters<typeof actual.apiFetch>) => apiFetchMock(...args) };
});

import { realTeamService } from './team-service.real';

function team(id: string): Team {
  return {
    id,
    name: 'Support',
    description: null,
    isActive: true,
    sortOrder: 0,
    members: [],
    memberCount: 0,
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-01T00:00:00Z',
  };
}

describe('realTeamService', () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
  });

  it('list() sends snake_case page/page_size/search/sort_by/sort_dir', async () => {
    apiFetchMock.mockResolvedValue({ data: [team('t1')], total: 1 });
    await realTeamService.list({
      page: 1,
      pageSize: 25,
      search: 'sup',
      sort: { id: 'name', desc: true },
    });
    const url = apiFetchMock.mock.calls[0][0] as string;
    expect(url).toContain('/teams?');
    expect(url).toContain('page=1');
    expect(url).toContain('page_size=25');
    expect(url).toContain('search=sup');
    expect(url).toContain('sort_by=name');
    expect(url).toContain('sort_dir=desc');
  });

  it('list() maps the shell column id "created" to the backend sort key "createdAt"', async () => {
    apiFetchMock.mockResolvedValue({ data: [], total: 0 });
    await realTeamService.list({ page: 0, pageSize: 25, sort: { id: 'created', desc: false } });
    const url = apiFetchMock.mock.calls[0][0] as string;
    expect(url).toContain('sort_by=createdAt');
  });

  it('getAt() hits /teams/at with index + search + sort', async () => {
    apiFetchMock.mockResolvedValue({ team: team('t1'), total: 1 });
    await realTeamService.getAt({ page: 0, pageSize: 25, search: 'x', sort: null }, 3);
    const url = apiFetchMock.mock.calls[0][0] as string;
    expect(url).toContain('/teams/at?');
    expect(url).toContain('index=3');
    expect(url).toContain('search=x');
  });

  it('mine() hits GET /teams/mine with no params', async () => {
    apiFetchMock.mockResolvedValue([team('t1')]);
    const result = await realTeamService.mine();
    expect(apiFetchMock).toHaveBeenCalledWith('/teams/mine');
    expect(result).toEqual([team('t1')]);
  });

  it('create() POSTs the raw input body (plain camelCase, no remapping)', async () => {
    apiFetchMock.mockResolvedValue(team('t1'));
    const input = { name: 'Support', members: [{ userId: 'u1', role: 'lead' as const }] };
    await realTeamService.create(input);
    expect(apiFetchMock).toHaveBeenCalledWith('/teams', {
      method: 'POST',
      body: JSON.stringify(input),
    });
  });

  it('update() PATCHes /teams/{id}', async () => {
    apiFetchMock.mockResolvedValue(team('t1'));
    await realTeamService.update('t1', { name: 'Renamed' });
    expect(apiFetchMock).toHaveBeenCalledWith('/teams/t1', {
      method: 'PATCH',
      body: JSON.stringify({ name: 'Renamed' }),
    });
  });

  it('remove() DELETEs /teams/{id}', async () => {
    apiFetchMock.mockResolvedValue(undefined);
    await realTeamService.remove('t1');
    expect(apiFetchMock).toHaveBeenCalledWith('/teams/t1', { method: 'DELETE' });
  });
});
