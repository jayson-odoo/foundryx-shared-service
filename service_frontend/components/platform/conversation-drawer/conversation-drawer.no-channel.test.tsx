/**
 * Lane SS-CHANNEL-SKIP - a thread whose workspace has no active channel (e.g.
 * migrated before the number was connected) shows the no-channel banner +
 * Connect channel link, not the 24-hour template lock.
 */
import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Channel } from '@/types/omnichannel';
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
const channels = { listByWorkspace: vi.fn() };
vi.mock('@/services/channel-service', () => ({
  get channelService() {
    return channels;
  },
}));

describe('ConversationDrawer - no channel connected', () => {
  beforeEach(async () => {
    const { __mockResetConversations } = await import('@/services/conversation-service.mock');
    __mockResetConversations();
    Element.prototype.scrollIntoView = vi.fn();
    channels.listByWorkspace.mockReset();
  });

  it('closed window + no active channel: the no-channel banner replaces the 24-hour lock', async () => {
    channels.listByWorkspace.mockResolvedValue([]);
    render(<ConversationDrawer contactId="cnt-002" />);
    expect(await screen.findByTestId('no-channel-banner')).toHaveTextContent(
      'No active channel is connected to this workspace.',
    );
    expect(screen.queryByTestId('csw-banner')).not.toBeInTheDocument();
    expect(channels.listByWorkspace).toHaveBeenCalledWith('wsp-001');
  });

  it('control: an active channel keeps the 24-hour template lock', async () => {
    channels.listByWorkspace.mockResolvedValue([{ id: 'c1', isActive: true, isTrashed: false } as Channel]);
    render(<ConversationDrawer contactId="cnt-002" />);
    expect(await screen.findByTestId('csw-banner')).toBeInTheDocument();
    await waitFor(() => expect(channels.listByWorkspace).toHaveBeenCalled());
    expect(screen.queryByTestId('no-channel-banner')).not.toBeInTheDocument();
  });
});
