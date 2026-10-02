import { renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@/services/team-service', () => ({
  teamService: { list: vi.fn(), get: vi.fn(), getAt: vi.fn(), mine: vi.fn(), create: vi.fn(), update: vi.fn(), remove: vi.fn() },
}));
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock('next-auth/react', () => ({
  useSession: () => ({ status: 'authenticated', data: null }),
}));
vi.mock('@/hooks/use-terminology', () => ({
  useTerminology: () => ({ label: () => 'Team', labelPlural: () => 'Teams' }),
}));

import { useTeamsListConfig } from './use-teams-list-config';

describe('useTeamsListConfig (plan 28)', () => {
  it('exposes the required columns (Name, Description, Members, Status, Created)', () => {
    const { result } = renderHook(() => useTeamsListConfig());
    const ids = result.current.columns.map((c) => c.id);
    expect(ids).toEqual(
      expect.arrayContaining(['select', 'name', 'description', 'members', 'status', 'created', 'actions']),
    );
  });

  it('gates create + writes behind teams.manage; reads behind teams.read', () => {
    const { result } = renderHook(() => useTeamsListConfig());
    expect(result.current.createPermission).toBe('teams.manage');
    const edit = result.current.actions.find((a) => a.id === 'edit');
    const del = result.current.actions.find((a) => a.id === 'delete');
    expect(edit?.permission).toBe('teams.manage');
    expect(del?.permission).toBe('teams.manage');
  });

  it('has no Active|Trashed segmented control - a team has no soft-trash concept', () => {
    const { result } = renderHook(() => useTeamsListConfig());
    expect(result.current.enableStatusViews).toBe(false);
  });

  it('never hand-rolls a table - it is a ResourceListConfig consumed by <ResourceList>', () => {
    const { result } = renderHook(() => useTeamsListConfig());
    expect(typeof result.current.fetcher).toBe('function');
    expect(typeof result.current.rowHref).toBe('function');
  });
});
