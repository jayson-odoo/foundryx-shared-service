/**
 * `useTeamSettings` (plan 28, roadmap A8, AC-TEM-28/50) - merges the
 * per-workspace configured strategy rows onto the tenant's full ACTIVE team
 * catalog, defaulting an unconfigured team to `round_robin` (mirrors the
 * backend's own "no row = round_robin" default).
 */
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { Team } from '@/types/team';
import type { TeamAssignmentSetting } from '@/types/omnichannel';

const listTeamsMock = vi.fn();
vi.mock('@/hooks/use-teams', () => ({
  useTeams: () => {
    const result = listTeamsMock();
    return { teams: result, isLoading: false, error: null, reload: vi.fn() };
  },
}));

const listSettingsMock = vi.fn();
const setStrategyMock = vi.fn();
vi.mock('@/services/team-settings-service', () => ({
  teamSettingsService: {
    list: (...args: unknown[]) => listSettingsMock(...args),
    setStrategy: (...args: unknown[]) => setStrategyMock(...args),
  },
}));

import { useTeamSettings } from './use-team-settings';

function team(id: string, name: string): Team {
  return {
    id,
    name,
    description: null,
    isActive: true,
    sortOrder: 0,
    members: [],
    memberCount: 0,
    createdAt: '2026-01-01T00:00:00Z',
    updatedAt: '2026-01-02T00:00:00Z',
  };
}

function setting(over: Partial<TeamAssignmentSetting>): TeamAssignmentSetting {
  return {
    teamId: 't1',
    teamName: 'Support',
    strategy: 'round_robin',
    lastAssignedUserId: null,
    updatedAt: '2026-01-03T00:00:00Z',
    ...over,
  };
}

describe('useTeamSettings', () => {
  beforeEach(() => {
    listTeamsMock.mockReset();
    listSettingsMock.mockReset();
    setStrategyMock.mockReset();
  });

  it('defaults an unconfigured active team to round_robin', async () => {
    listTeamsMock.mockReturnValue([team('t1', 'Support')]);
    listSettingsMock.mockResolvedValue([]);

    const { result } = renderHook(() => useTeamSettings('wsp-1'));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.rows).toEqual([
      { teamId: 't1', teamName: 'Support', strategy: 'round_robin', lastAssignedUserId: null, updatedAt: '2026-01-02T00:00:00Z', isConfigured: false },
    ]);
  });

  it('surfaces the configured strategy + cursor for a team with a settings row', async () => {
    listTeamsMock.mockReturnValue([team('t1', 'Support')]);
    listSettingsMock.mockResolvedValue([setting({ strategy: 'least_open', lastAssignedUserId: 'u1' })]);

    const { result } = renderHook(() => useTeamSettings('wsp-1'));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.rows[0]).toEqual({
      teamId: 't1', teamName: 'Support', strategy: 'least_open', lastAssignedUserId: 'u1',
      updatedAt: '2026-01-03T00:00:00Z', isConfigured: true,
    });
  });

  it('setStrategy() calls the service and merges the result back onto the row', async () => {
    listTeamsMock.mockReturnValue([team('t1', 'Support')]);
    listSettingsMock.mockResolvedValue([]);
    setStrategyMock.mockResolvedValue(setting({ strategy: 'least_open' }));

    const { result } = renderHook(() => useTeamSettings('wsp-1'));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      await result.current.setStrategy('t1', 'least_open');
    });

    expect(setStrategyMock).toHaveBeenCalledWith('wsp-1', 't1', 'least_open');
    expect(result.current.rows[0].strategy).toBe('least_open');
    expect(result.current.rows[0].isConfigured).toBe(true);
  });

  it('no workspace id -> no fetch, empty rows', async () => {
    listTeamsMock.mockReturnValue([team('t1', 'Support')]);
    const { result } = renderHook(() => useTeamSettings(null));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(listSettingsMock).not.toHaveBeenCalled();
    // Still lists the team catalog defaulted to round_robin - the row set is
    // driven by teams, but with no workspace there is nothing configured.
    expect(result.current.rows[0].isConfigured).toBe(false);
  });
});
