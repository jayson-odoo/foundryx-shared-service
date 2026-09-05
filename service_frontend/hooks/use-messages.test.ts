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

// The binding points at the REAL service since Phase B - pin the hooks to the
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

  it('F1: a slow patchContact for the PREVIOUS contact does not overwrite the newly selected thread', async () => {
    const { mockConversationService } = await import('@/services/conversation-service.mock');

    let resolvePatch!: (thread: import('@/types/omnichannel').ConversationThread) => void;
    const pending = new Promise<import('@/types/omnichannel').ConversationThread>((resolve) => {
      resolvePatch = resolve;
    });
    const spy = vi.spyOn(mockConversationService, 'patchContact').mockReturnValue(pending);

    const { result, rerender } = renderHook(({ id }: { id: string }) => useMessages(id), {
      initialProps: { id: 'cnt-001' },
    });
    await waitFor(() => expect(result.current.thread?.id).toBe('cnt-001'));

    // Fire a patch for cnt-001 but never let it resolve yet.
    let patchPromise!: Promise<unknown>;
    act(() => {
      patchPromise = result.current.patchContact({ firstName: 'Stale Edit' });
    });

    // User switches to a different contact before the patch above resolves.
    rerender({ id: 'cnt-002' });
    await waitFor(() => expect(result.current.thread?.id).toBe('cnt-002'));

    // NOW the stale patch resolves - it must NOT clobber the newly selected thread.
    const staleThread = await mockConversationService.getThread('cnt-001');
    await act(async () => {
      resolvePatch({ ...staleThread, firstName: 'Stale Edit' });
      await patchPromise;
    });

    expect(result.current.thread?.id).toBe('cnt-002');
    spy.mockRestore();
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

  it('F2: an event for a DIFFERENT workspace is ignored, not upserted into the list', async () => {
    const { mockConversationService } = await import('@/services/conversation-service.mock');
    const spy = vi.spyOn(mockConversationService, 'subscribe');

    const { result } = renderHook(() => useConversations('wsp-001'));
    await waitFor(() => expect(result.current.threads.length).toBeGreaterThan(0));
    const before = result.current.threads.length;

    const handler = spy.mock.calls[0][1];
    act(() => {
      handler({
        type: 'contact.updated',
        thread: {
          ...result.current.threads[0],
          id: 'cnt-foreign-workspace',
          workspaceId: 'wsp-999',
        },
      });
    });

    // No new row from the foreign workspace, and the list is unchanged.
    expect(result.current.threads.some((t) => t.id === 'cnt-foreign-workspace')).toBe(false);
    expect(result.current.threads.length).toBe(before);
    spy.mockRestore();
  });
});
