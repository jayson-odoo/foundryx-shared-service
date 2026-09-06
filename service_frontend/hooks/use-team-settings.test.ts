/**
 * `useTeamSettings` (plan 28, roadmap A8, AC-TEM-28/50). Review round 1,
 * finding 4/5/6: the backend now returns one row per ACTIVE core team
 * already merged with any configured strategy, so this hook is a thin
 * fetch/reload wrapper over `teamSettingsService.list` - it no longer calls
 * `useTeams` (`GET /teams`, gated `teams.read`) to build the roster.
 */
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { TeamAssignmentSetting } from '@/types/omnichannel';

const listSettingsMock = vi.fn();
const setStrategyMock = vi.fn();
vi.mock('@/services/team-settings-service', () => ({
  teamSettingsService: {
    list: (...args: unknown[]) => listSettingsMock(...args),
    setStrategy: (...args: unknown[]) => setStrategyMock(...args),
  },
}));

import { useTeamSettings } from './use-team-settings';

function setting(over: Partial<TeamAssignmentSetting>): TeamAssignmentSetting {
  return {
    teamId: 't1',
    teamName: 'Support',
    strategy: 'round_robin',
    lastAssignedUserId: null,
    updatedAt: null,
    isConfigured: false,
    ...over,
  };
}

describe('useTeamSettings', () => {
  beforeEach(() => {
    listSettingsMock.mockReset();
    setStrategyMock.mockReset();
  });

  it('renders whatever rows the backend returns (already merged with the active-team roster)', async () => {
    listSettingsMock.mockResolvedValue([setting({})]);

    const { result } = renderHook(() => useTeamSettings('wsp-1'));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.rows).toEqual([
      { teamId: 't1', teamName: 'Support', strategy: 'round_robin', lastAssignedUserId: null, updatedAt: null, isConfigured: false },
    ]);
    expect(listSettingsMock).toHaveBeenCalledWith('wsp-1');
  });

  it('surfaces a configured team as-is', async () => {
    listSettingsMock.mockResolvedValue([
      setting({ strategy: 'least_open', lastAssignedUserId: 'u1', updatedAt: '2026-01-03T00:00:00Z', isConfigured: true }),
    ]);

    const { result } = renderHook(() => useTeamSettings('wsp-1'));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.rows[0]).toEqual({
      teamId: 't1', teamName: 'Support', strategy: 'least_open', lastAssignedUserId: 'u1',
      updatedAt: '2026-01-03T00:00:00Z', isConfigured: true,
    });
  });

  it('setStrategy() calls the service and replaces the row with the server response', async () => {
    listSettingsMock.mockResolvedValue([setting({})]);
    setStrategyMock.mockResolvedValue(setting({ strategy: 'least_open', isConfigured: true }));

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
    const { result } = renderHook(() => useTeamSettings(null));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(listSettingsMock).not.toHaveBeenCalled();
    expect(result.current.rows).toEqual([]);
  });

  it('surfaces a fetch error', async () => {
    listSettingsMock.mockRejectedValue(new Error('nope'));
    const { result } = renderHook(() => useTeamSettings('wsp-1'));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.error).toBe('nope');
  });
});
