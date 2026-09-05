/**
 * TeamRail (plan 28, roadmap A8, AC-TEM-44 slice content) - selection ->
 * `onSelect(teamId, unassignedOnly)`, at both the >=1024px rail and the
 * <1024px SearchSelect. `use-conversations.test.ts` covers the query-param
 * side of "selection -> URL".
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { TeamRail } from './team-rail';

let isDesktop = true;
vi.mock('@/hooks/use-media-query', () => ({
  useMediaQuery: () => isDesktop,
}));

let canAssign = false;
vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: (key: string) => key === 'conversations.assign' && canAssign, ready: true, permissions: new Set() }),
}));

const MY_TEAMS = [
  { id: 'team-1', name: 'Sales', description: null, isActive: true, sortOrder: 0, members: [], memberCount: 0, createdAt: '', updatedAt: '' },
];
const ALL_TEAMS = [
  ...MY_TEAMS,
  { id: 'team-2', name: 'Support', description: null, isActive: true, sortOrder: 1, members: [], memberCount: 0, createdAt: '', updatedAt: '' },
];
vi.mock('@/hooks/use-my-teams', () => ({
  useMyTeams: () => ({ teams: MY_TEAMS, isLoading: false, error: null, reload: vi.fn() }),
}));
vi.mock('@/hooks/use-teams', () => ({
  useTeams: () => ({ teams: ALL_TEAMS, isLoading: false, error: null, reload: vi.fn() }),
}));

describe('TeamRail', () => {
  beforeEach(() => {
    isDesktop = true;
    canAssign = false;
  });

  it('renders My teams with a nested Unassigned entry and selects on click (desktop)', async () => {
    const onSelect = vi.fn();
    const user = userEvent.setup();
    render(<TeamRail selectedTeamId={null} selectedAssignee="all" onSelect={onSelect} />);

    expect(await screen.findByTestId('team-rail')).toBeInTheDocument();
    expect(screen.getByTestId('team-rail-team-1')).toHaveTextContent('Sales');
    // Not privileged - no "All teams" group, so Support (not mine) is absent.
    expect(screen.queryByText('Support')).not.toBeInTheDocument();

    await user.click(screen.getByTestId('team-rail-team-1'));
    expect(onSelect).toHaveBeenCalledWith('team-1', false);

    await user.click(screen.getByTestId('team-rail-team-1-unassigned'));
    expect(onSelect).toHaveBeenCalledWith('team-1', true);

    await user.click(screen.getByTestId('team-rail-all'));
    expect(onSelect).toHaveBeenCalledWith(null, false);
  });

  it('shows an All teams group for conversations.assign holders', async () => {
    canAssign = true;
    render(<TeamRail selectedTeamId={null} selectedAssignee="all" onSelect={vi.fn()} />);
    expect(await screen.findByText('All teams')).toBeInTheDocument();
    expect(screen.getByTestId('team-rail-team-2')).toHaveTextContent('Support');
  });

  it('renders a searchable select below 1024px with the same entries', async () => {
    isDesktop = false;
    const onSelect = vi.fn();
    const user = userEvent.setup();
    render(<TeamRail selectedTeamId={null} selectedAssignee="all" onSelect={onSelect} />);

    const trigger = await screen.findByRole('combobox', { name: 'Team Inbox' });
    await user.click(trigger);
    const option = await screen.findByText('Sales - Unassigned');
    await user.click(option);

    await waitFor(() => expect(onSelect).toHaveBeenCalledWith('team-1', true));
  });
});
