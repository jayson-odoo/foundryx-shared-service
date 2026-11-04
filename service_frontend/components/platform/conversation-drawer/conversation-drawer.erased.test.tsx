/**
 * Plan 56 C, AC-56-48 - a drawer whose contact was erased leaves the loading
 * skeleton and shows its empty state; a drawer that is simply still loading
 * keeps the skeleton (control).
 */
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ConversationDrawer } from './conversation-drawer';

const messagesState = vi.hoisted(() => ({ value: {} as Record<string, unknown> }));

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
vi.mock('@/services/channel-service', () => ({
  channelService: { listByWorkspace: vi.fn(async () => []) },
}));
vi.mock('@/hooks/use-messages', () => ({
  useMessages: () => messagesState.value,
}));

const noop = vi.fn(async () => undefined);
const base = {
  thread: null,
  messages: [],
  isLoading: true,
  error: null,
  erased: false,
  isSending: false,
  sendError: null,
  send: noop,
  sendTemplate: noop,
  sendMedia: noop,
  sendInteractive: noop,
  sendLocation: noop,
  sendContacts: noop,
  react: noop,
  addNote: noop,
  assign: noop,
  assignToMe: noop,
  assignTeam: noop,
  setStatus: noop,
  closeThread: noop,
  patchContact: noop,
  moveLifecycle: noop,
};

describe('ConversationDrawer - erased contact', () => {
  beforeEach(() => {
    Element.prototype.scrollIntoView = vi.fn();
  });

  it('shows the empty state, never a skeleton, once its contact is erased', () => {
    messagesState.value = { ...base, erased: true };
    render(<ConversationDrawer contactId="cnt-erased" emptyHint="Select a conversation" />);
    expect(screen.getByTestId('drawer-empty')).toHaveTextContent('Select a conversation');
    expect(screen.queryByTestId('drawer-loading')).not.toBeInTheDocument();
  });

  it('control: a contact that is only loading keeps the skeleton', () => {
    messagesState.value = { ...base, erased: false };
    render(<ConversationDrawer contactId="cnt-loading" />);
    expect(screen.getByTestId('drawer-loading')).toBeInTheDocument();
    expect(screen.queryByTestId('drawer-empty')).not.toBeInTheDocument();
  });
});
