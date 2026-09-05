/**
 * Conversation drawer - Teams group on the assignee dropdown (plan 28,
 * roadmap A8, AC-TEM-45/47). S0 mock: `teamAssignmentService` + `useTeams`
 * are mocked directly so this test targets the drawer's wiring, not the
 * mock service internals (covered separately).
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ConversationDrawer } from './conversation-drawer';

vi.mock('next-auth/react', () => ({
  useSession: () => ({ status: 'authenticated', data: null }),
}));

vi.mock('@/services/conversation-service', async () => {
  const { mockConversationService } = await import('@/services/conversation-service.mock');
  return { conversationService: mockConversationService };
});
vi.mock('@/services/workspace-service', () => ({
  workspaceService: { getMembers: vi.fn(async () => []) },
}));

const assignTeamMock = vi.fn();
const overlayForMock = vi.fn(() => ({ assignedTeamId: null, assignedTeamName: null }));
vi.mock('@/services/team-assignment-service', () => ({
  teamAssignmentService: {
    assignTeam: (...args: unknown[]) => assignTeamMock(...args),
    overlayFor: (...args: unknown[]) => overlayForMock(...args),
  },
}));

vi.mock('@/hooks/use-teams', () => ({
  useTeams: () => ({
    teams: [{ id: 'team-1', name: 'Support', description: null, isActive: true, sortOrder: 0, members: [], memberCount: 0, createdAt: '', updatedAt: '' }],
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
    assignTeamMock.mockReset();
    overlayForMock.mockReturnValue({ assignedTeamId: null, assignedTeamName: null });
    toastError.mockReset();
  });

  it('lists a Teams group in the assignee dropdown and assigns on click', async () => {
    assignTeamMock.mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<ConversationDrawer contactId="cnt-001" />);

    await waitFor(() => expect(screen.getByTestId('assign-trigger')).toBeInTheDocument());
    await user.click(screen.getByTestId('assign-trigger'));

    expect(await screen.findByText('Teams')).toBeInTheDocument();
    const teamItem = screen.getByTestId('assign-team-team-1');
    expect(teamItem).toHaveTextContent('Support');

    await user.click(teamItem);
    await waitFor(() => expect(assignTeamMock).toHaveBeenCalledWith('cnt-001', 'team-1'));
  });

  it('reverts (no state change) and toasts the server message on a failed assign', async () => {
    assignTeamMock.mockRejectedValue(new Error('Please fix the highlighted fields.'));
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
