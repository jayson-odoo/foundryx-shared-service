/**
 * Plan 56 C, AC-56-48 - the realtime `{type: 'contact.erased', contactId}` event drops the
 * contact from the inbox list and closes an open thread, with no reload and no refetch.
 * Seams: `ConversationSocketEvent` gains that variant; `useConversations` removes the
 * thread; `useMessages` exposes `erased: true` and empties `thread` / `messages` when the
 * event names its contact (the drawer/inbox closes on it).
 */
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { ConversationSocketEvent, ConversationThread } from '@/types/omnichannel';

const { listThreadsMock, getThreadMock, listMessagesMock, subscribeMock } = vi.hoisted(() => ({
  listThreadsMock: vi.fn(),
  getThreadMock: vi.fn(),
  listMessagesMock: vi.fn(),
  subscribeMock: vi.fn(),
}));
vi.mock('@/services/conversation-service', () => ({
  conversationService: {
    listThreads: listThreadsMock,
    getThread: getThreadMock,
    listMessages: listMessagesMock,
    subscribe: subscribeMock,
  },
}));

import { useConversations } from './use-conversations';
import { useMessages } from './use-messages';

function thread(id: string): ConversationThread {
  return {
    id, workspaceId: 'wsp-1', firstName: null, lastName: null, phone: '+60000000000', name: id,
    status: 'OPEN', priority: 'MEDIUM', assignedUserId: null, assignedUserName: null,
    lastMessageAt: '2026-01-01T00:00:00Z', lastMessagePreview: null, unreadCount: 0, channelId: null,
    cswExpiresAt: null, assignedTeamId: null, assignedTeamName: null, tags: [], customFields: {},
  } as unknown as ConversationThread;
}

let handlers: Array<(e: ConversationSocketEvent) => void> = [];
const erasedEvent = (contactId: string) => ({ type: 'contact.erased', contactId }) as unknown as ConversationSocketEvent;

beforeEach(() => {
  vi.clearAllMocks();
  handlers = [];
  subscribeMock.mockImplementation((_ws: string, cb: (e: ConversationSocketEvent) => void) => {
    handlers.push(cb);
    return () => {};
  });
  window.history.replaceState(null, '', '/omnichannel/inbox');
});

describe('useConversations', () => {
  it('drops the erased contact from the list without refetching', async () => {
    listThreadsMock.mockResolvedValue([thread('cnt-1'), thread('cnt-2')]);
    const { result } = renderHook(() => useConversations('wsp-1'));
    await waitFor(() => expect(result.current.threads).toHaveLength(2));
    const fetches = listThreadsMock.mock.calls.length;

    act(() => handlers.forEach((h) => h(erasedEvent('cnt-1'))));

    await waitFor(() => expect(result.current.threads.map((t) => t.id)).toEqual(['cnt-2']));
    expect(listThreadsMock.mock.calls.length).toBe(fetches);
  });

  it('an event for a contact that is not in the list changes nothing and does not throw', async () => {
    listThreadsMock.mockResolvedValue([thread('cnt-1')]);
    const { result } = renderHook(() => useConversations('wsp-1'));
    await waitFor(() => expect(result.current.threads).toHaveLength(1));
    act(() => handlers.forEach((h) => h(erasedEvent('cnt-unknown'))));
    expect(result.current.threads.map((t) => t.id)).toEqual(['cnt-1']);
  });
});

describe('useMessages', () => {
  it('marks the open thread erased and clears it when its own contact is erased', async () => {
    getThreadMock.mockResolvedValue(thread('cnt-1'));
    listMessagesMock.mockResolvedValue([]);
    const { result } = renderHook(() => useMessages('cnt-1'));
    await waitFor(() => expect(result.current.thread?.id).toBe('cnt-1'));
    expect((result.current as unknown as { erased: boolean }).erased).toBe(false);

    act(() => handlers.forEach((h) => h(erasedEvent('cnt-1'))));

    await waitFor(() => expect((result.current as unknown as { erased: boolean }).erased).toBe(true));
    expect(result.current.thread).toBeNull();
    expect(result.current.messages).toEqual([]);
  });

  it('ignores an erase of another contact', async () => {
    getThreadMock.mockResolvedValue(thread('cnt-1'));
    listMessagesMock.mockResolvedValue([]);
    const { result } = renderHook(() => useMessages('cnt-1'));
    await waitFor(() => expect(result.current.thread?.id).toBe('cnt-1'));
    act(() => handlers.forEach((h) => h(erasedEvent('cnt-2'))));
    expect((result.current as unknown as { erased: boolean }).erased).toBe(false);
    expect(result.current.thread?.id).toBe('cnt-1');
  });
});
