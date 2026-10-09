import { renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const list = vi.fn();
vi.mock('@/services/team-service', () => ({
  teamService: { list: (...args: unknown[]) => list(...args) },
}));

import { useTeams } from './use-teams';

const TEAM = (over: Record<string, unknown> = {}) => ({
  id: 't1', name: 'Sales', description: null, isActive: true, sortOrder: 0,
  members: [], memberCount: 0, createdAt: '', updatedAt: '', ...over,
});

describe('useTeams', () => {
  it('filters to active teams by default (foolproof-UI)', async () => {
    list.mockResolvedValue({ data: [TEAM(), TEAM({ id: 't2', isActive: false })], total: 2, page: 0 });
    const { result } = renderHook(() => useTeams());
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.teams.map((t) => t.id)).toEqual(['t1']);
  });

  it('activeOnly=false includes inactive teams', async () => {
    list.mockResolvedValue({ data: [TEAM(), TEAM({ id: 't2', isActive: false })], total: 2, page: 0 });
    const { result } = renderHook(() => useTeams({ activeOnly: false }));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.teams.map((t) => t.id)).toEqual(['t1', 't2']);
  });
});
