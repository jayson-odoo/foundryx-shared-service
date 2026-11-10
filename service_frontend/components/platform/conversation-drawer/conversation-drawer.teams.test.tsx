/**
 * Conversation drawer - Teams group on the assignee dropdown (plan 28,
 * roadmap A8, AC-TEM-45/47). `useTeams` is mocked directly; team assignment
 * rides the real `conversationService.patchContact` (S5 wire - the real
 * backend contract is `PATCH /omnichannel/contacts/{id} {assignedTeamId}`),
 * with `patchContact` overridden here so this test targets the drawer's
 * wiring, not the mock service's internals.
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ConversationDrawer } from './conversation-drawer';

vi.mock('next-auth/react', () => ({
  useSession: () => ({ status: 'authenticated', data: null }),
}));

const patchContactMock = vi.fn();
vi.mock('@/services/conversation-service', async () => {
  const { mockConversationService } = await import('@/services/conversation-service.mock');
  return {
    conversationService: {
      ...mockConversationService,
      patchContact: (...args: unknown[]) => patchContactMock(...args),
    },
  };
});
vi.mock('@/services/workspace-service', () => ({
  workspaceService: { getMembers: vi.fn(async () => []) },
}));

vi.mock('@/hooks/use-teams', () => ({
  useTeams: () => ({
    teams: [{ id: 'team-1', name: 'Support', description: null, isActive: true, sortOrder: 0, members: [], memberCount: 0, createdAt: '', updatedAt: '' }],
    isLoading: false,
    error: null,
    reload: vi.fn(),
  }),
}));

// Review round 2, N1: `/teams/mine` carries inactive teams too (no
// is_active filter server-side) - the union must drop them, or a click
// 422s on the PATCH.
vi.mock('@/hooks/use-my-teams', () => ({
  useMyTeams: () => ({
    teams: [
      { id: 'team-1', name: 'Support', isActive: true, memberCount: 0, members: [] },
      { id: 'team-mine-2', name: 'Retention', isActive: true, memberCount: 1, members: [] },
      { id: 'team-old', name: 'Legacy Desk', isActive: false, memberCount: 1, members: [] },
    ],
    isLoading: false,
    error: null,
    reload: vi.fn(),
  }),
}));

const toastError = vi.fn();
vi.mock('@/lib/toast', () => ({
  toast: { success: vi.fn(), error: (...args: unknown[]) => toastError(...args), info: vi.fn(), warning: vi.fn() },
}));

describe('ConversationDrawer - Teams group (plan 28)', () => {
  beforeEach(() => {
    patchContactMock.mockReset();
    toastError.mockReset();
  });

  it('lists a Teams group in the assignee dropdown and assigns on click', async () => {
    // The real `PATCH` returns the FULL resolved ThreadItem (assignee +
    // team both authoritative in one round trip) - mirror that shape here
    // rather than a partial object the drawer might read undefined fields
    // off of.
    const { mockConversationService } = await import('@/services/conversation-service.mock');
    const base = await mockConversationService.getThread('cnt-001');
    patchContactMock.mockResolvedValue({ ...base, assignedTeamId: 'team-1', assignedTeamName: 'Support' });
    const user = userEvent.setup();
    render(<ConversationDrawer contactId="cnt-001" />);

    await waitFor(() => expect(screen.getByTestId('assign-trigger')).toBeInTheDocument());
    await user.click(screen.getByTestId('assign-trigger'));

    expect(await screen.findByText('Teams')).toBeInTheDocument();
    const teamItem = screen.getByTestId('assign-team-team-1');
    expect(teamItem).toHaveTextContent('Support');

    await user.click(teamItem);
    await waitFor(() =>
      expect(patchContactMock).toHaveBeenCalledWith('cnt-001', { assignedTeamId: 'team-1' }),
    );
  });

  it('N1: unions my teams with all teams, deduped, and never offers an INACTIVE team', async () => {
    const user = userEvent.setup();
    render(<ConversationDrawer contactId="cnt-001" />);

    await waitFor(() => expect(screen.getByTestId('assign-trigger')).toBeInTheDocument());
    await user.click(screen.getByTestId('assign-trigger'));
    expect(await screen.findByText('Teams')).toBeInTheDocument();

    // team-1 comes from BOTH sources - rendered once.
    expect(screen.getAllByTestId('assign-team-team-1')).toHaveLength(1);
    // my-teams-only active team is offered.
    expect(screen.getByTestId('assign-team-team-mine-2')).toHaveTextContent('Retention');
    // inactive team from /teams/mine is NOT offered.
    expect(screen.queryByTestId('assign-team-team-old')).not.toBeInTheDocument();
    expect(screen.queryByText('Legacy Desk')).not.toBeInTheDocument();
  });

  it('reverts (no state change) and toasts the server message on a failed assign', async () => {
    patchContactMock.mockRejectedValue(new Error('Please fix the highlighted fields.'));
    const user = userEvent.setup();
    render(<ConversationDrawer contactId="cnt-001" />);

    await waitFor(() => expect(screen.getByTestId('assign-trigger')).toBeInTheDocument());
    // Baseline: the seeded thread's real assignee, no team.
    expect(screen.getByTestId('assign-trigger')).toHaveTextContent('Demo User');

    await user.click(screen.getByTestId('assign-trigger'));
    await user.click(screen.getByTestId('assign-team-team-1'));

    await waitFor(() => expect(toastError).toHaveBeenCalledWith('Please fix the highlighted fields.'));
    // Nothing was set optimistically - the header still shows the real assignee.
    expect(screen.getByTestId('assign-trigger')).toHaveTextContent('Demo User');
  });
});
