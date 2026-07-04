/**
 * Inbox hooks behaviour against the mock service (plan 05 Phase A).
 */
import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  MOCK_CURRENT_USER,
  __mockResetConversations,
  __mockSimulateInbound,
} from '@/services/conversation-service.mock';

// The binding points at the REAL service since Phase B — pin the hooks to the
// mock here (deterministic, no backend/session in jsdom).
vi.mock('@/services/conversation-service', async () => {
  const { mockConversationService } = await import('@/services/conversation-service.mock');
  return { conversationService: mockConversationService };
});

import { useConversations } from './use-conversations';
import { useMessages } from './use-messages';

beforeEach(() => {
  __mockResetConversations();
});

describe('useMessages', () => {
  it('loads thread + messages', async () => {
    const { result } = renderHook(() => useMessages('cnt-001'));
    await waitFor(() => expect(result.current.thread?.name).toBe('Sarah Chen'));
    expect(result.current.messages.length).toBeGreaterThan(0);
    expect(result.current.messages[0].createdAt <= result.current.messages.at(-1)!.createdAt).toBe(true);
  });

  it('appends a live inbound message via the socket', async () => {
    const { result } = renderHook(() => useMessages('cnt-001'));
    await waitFor(() => expect(result.current.thread).not.toBeNull());
    const before = result.current.messages.length;

    act(() => __mockSimulateInbound('wsp-001', 'cnt-001'));

    await waitFor(() => expect(result.current.messages.length).toBe(before + 1));
    expect(result.current.messages.at(-1)!.senderType).toBe('CONTACT');
  });

  it('surfaces the CSW rejection as sendError, not a crash', async () => {
    const { result } = renderHook(() => useMessages('cnt-002')); // expired window
    await waitFor(() => expect(result.current.thread).not.toBeNull());

    let ok = true;
    await act(async () => {
      ok = await result.current.send({ messageType: 'TEXT', body: 'hello?' });
    });
    expect(ok).toBe(false);
    expect(result.current.sendError).toMatch(/24-hour window/);
  });

  it('send appends the agent bubble through the emitter (no duplicates)', async () => {
    const { result } = renderHook(() => useMessages('cnt-001'));
    await waitFor(() => expect(result.current.thread).not.toBeNull());
    const before = result.current.messages.length;

    await act(async () => {
      await result.current.send({ messageType: 'TEXT', body: 'On it!' });
    });

    await waitFor(() => expect(result.current.messages.length).toBe(before + 1));
    const last = result.current.messages.at(-1)!;
    expect(last.senderType).toBe('AGENT');
    expect(last.body).toBe('On it!');
  });

  it('addNote appends a SYSTEM bubble', async () => {
    const { result } = renderHook(() => useMessages('cnt-001'));
    await waitFor(() => expect(result.current.thread).not.toBeNull());

    await act(async () => {
      await result.current.addNote('Internal: VIP');
    });
    expect(result.current.messages.at(-1)!.senderType).toBe('SYSTEM');
  });
});

describe('useConversations', () => {
  it('loads workspace threads sorted by recency', async () => {
    const { result } = renderHook(() => useConversations('wsp-001'));
    await waitFor(() => expect(result.current.threads.length).toBeGreaterThan(0));
    const times = result.current.threads.map((t) => t.lastMessageAt ?? '');
    expect([...times].sort().reverse()).toEqual(times);
  });

  it('unassigned filter narrows the list', async () => {
    const { result } = renderHook(() => useConversations('wsp-001'));
    await waitFor(() => expect(result.current.threads.length).toBeGreaterThan(0));

    act(() => result.current.setFilters({ assignee: 'unassigned' }));
    await waitFor(() =>
      expect(result.current.threads.every((t) => t.assignedUserId === null)).toBe(true),
    );
    expect(result.current.threads.length).toBeGreaterThan(0);
  });

  it('live inbound bumps the thread to the top with unread count', async () => {
    const { result } = renderHook(() => useConversations('wsp-001'));
    await waitFor(() => expect(result.current.threads.length).toBeGreaterThan(0));

    act(() => __mockSimulateInbound('wsp-001', 'cnt-002'));

    await waitFor(() => expect(result.current.threads[0].id).toBe('cnt-002'));
    expect(result.current.threads[0].unreadCount).toBeGreaterThan(0);
  });

  it('self-claim is reflected via contact.updated', async () => {
    const conversations = renderHook(() => useConversations('wsp-001'));
    const messages = renderHook(() => useMessages('cnt-003'));
    await waitFor(() => expect(messages.result.current.thread).not.toBeNull());
    await waitFor(() => expect(conversations.result.current.threads.length).toBeGreaterThan(0));

    await act(async () => {
      await messages.result.current.assign(MOCK_CURRENT_USER.id);
    });

    await waitFor(() => {
      const row = conversations.result.current.threads.find((t) => t.id === 'cnt-003');
      expect(row?.assignedUserId).toBe(MOCK_CURRENT_USER.id);
    });
  });
});
