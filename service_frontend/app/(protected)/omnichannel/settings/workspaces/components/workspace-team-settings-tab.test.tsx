/**
 * Team assignment tab (plan 28, roadmap A8, AC-TEM-28) - renders one row per
 * active team with a strategy `SearchSelect`, gated `conversations.assign`
 * for editing (mirrors the backend's write gate).
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { WorkspaceTeamSettingsTab } from './workspace-team-settings-tab';

vi.mock('next-auth/react', () => ({
  useSession: () => ({ status: 'authenticated', data: null }),
}));

const { toastErrorMock } = vi.hoisted(() => ({ toastErrorMock: vi.fn() }));
vi.mock('@/lib/toast', () => ({
  toast: { error: toastErrorMock, success: vi.fn(), info: vi.fn(), warning: vi.fn() },
}));

const canMock = vi.fn(() => true);
vi.mock('@/hooks/use-can', () => ({ useCan: () => ({ can: canMock }) }));

const { useTeamSettingsMock, setStrategyMock } = vi.hoisted(() => ({
  useTeamSettingsMock: vi.fn(),
  setStrategyMock: vi.fn(),
}));
vi.mock('@/hooks/use-team-settings', () => ({ useTeamSettings: useTeamSettingsMock }));

function baseRows() {
  return [
    { teamId: 't1', teamName: 'Support', strategy: 'round_robin' as const, lastAssignedUserId: null, updatedAt: '2026-01-01T00:00:00Z', isConfigured: false },
    { teamId: 't2', teamName: 'Sales', strategy: 'least_open' as const, lastAssignedUserId: 'u1', updatedAt: '2026-01-02T00:00:00Z', isConfigured: true },
  ];
}

beforeEach(() => {
  toastErrorMock.mockReset();
  setStrategyMock.mockReset();
  canMock.mockReturnValue(true);
  useTeamSettingsMock.mockReturnValue({
    rows: baseRows(),
    isLoading: false,
    error: null,
    setStrategy: setStrategyMock,
    reload: vi.fn(),
  });
});

describe('WorkspaceTeamSettingsTab', () => {
  it('prompts to save the workspace first while creating', () => {
    render(<WorkspaceTeamSettingsTab workspaceId={null} creating />);
    expect(screen.getByText(/Save the workspace/i)).toBeInTheDocument();
  });

  it('shows an empty state with no active teams', () => {
    useTeamSettingsMock.mockReturnValue({ rows: [], isLoading: false, error: null, setStrategy: setStrategyMock, reload: vi.fn() });
    render(<WorkspaceTeamSettingsTab workspaceId="wsp-1" creating={false} />);
    expect(screen.getByText(/No teams yet/i)).toBeInTheDocument();
  });

  it('lists every active team with its current strategy', () => {
    render(<WorkspaceTeamSettingsTab workspaceId="wsp-1" creating={false} />);
    expect(screen.getByText('Support')).toBeInTheDocument();
    expect(screen.getByText('Sales')).toBeInTheDocument();
  });

  it('changing the strategy calls setStrategy(teamId, strategy)', async () => {
    setStrategyMock.mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<WorkspaceTeamSettingsTab workspaceId="wsp-1" creating={false} />);

    const trigger = screen.getByRole('combobox', { name: /Support assignment strategy/i });
    await user.click(trigger);
    await user.click(await screen.findByRole('option', { name: 'Least open threads' }));

    await waitFor(() => expect(setStrategyMock).toHaveBeenCalledWith('t1', 'least_open'));
  });

  it('toasts the server message when setStrategy() rejects', async () => {
    setStrategyMock.mockRejectedValue(new Error('Team not found.'));
    const user = userEvent.setup();
    render(<WorkspaceTeamSettingsTab workspaceId="wsp-1" creating={false} />);

    const trigger = screen.getByRole('combobox', { name: /Support assignment strategy/i });
    await user.click(trigger);
    await user.click(await screen.findByRole('option', { name: 'Least open threads' }));

    await waitFor(() => expect(toastErrorMock).toHaveBeenCalledWith('Team not found.'));
  });

  it('disables the strategy control without conversations.assign (foolproof-UI)', () => {
    canMock.mockReturnValue(false);
    render(<WorkspaceTeamSettingsTab workspaceId="wsp-1" creating={false} />);
    const trigger = screen.getByRole('combobox', { name: /Support assignment strategy/i });
    expect(trigger).toBeDisabled();
  });
});
