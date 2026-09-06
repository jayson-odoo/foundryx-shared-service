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

  // F11 (round-3 codex triage) - a note started for contact A must not
  // commit into contact B's message list once the user has switched, even
  // though the SAME `messages` state is shared by the hook instance.
  it('F11: a slow addNote for the PREVIOUS contact does not land in the newly selected contact\'s messages', async () => {
    const { mockConversationService } = await import('@/services/conversation-service.mock');

    let resolveNote!: (m: import('@/types/omnichannel').ConversationMessage) => void;
    const pending = new Promise<import('@/types/omnichannel').ConversationMessage>((resolve) => {
      resolveNote = resolve;
    });
    const spy = vi.spyOn(mockConversationService, 'addInternalNote').mockReturnValue(pending);

    const { result, rerender } = renderHook(({ id }: { id: string }) => useMessages(id), {
      initialProps: { id: 'cnt-001' },
    });
    await waitFor(() => expect(result.current.thread?.id).toBe('cnt-001'));

    let notePromise!: Promise<boolean>;
    act(() => {
      notePromise = result.current.addNote('Stale note for cnt-001');
    });

    // User switches to a different contact before the note above resolves.
    rerender({ id: 'cnt-002' });
    await waitFor(() => expect(result.current.thread?.id).toBe('cnt-002'));
    const cnt002MessageCount = result.current.messages.length;

    // NOW the stale note resolves - it must NOT be appended to cnt-002's list.
    await act(async () => {
      resolveNote({
        id: 'msg-stale-note', contactId: 'cnt-001', channelId: null, senderType: 'SYSTEM',
        senderId: null, senderName: null, messageType: 'TEXT', body: 'Stale note for cnt-001',
        mediaUrl: null, mediaMime: null, mediaFilename: null, mediaSize: null, voice: false, payload: null,
        reactions: [], externalMessageId: null, deliveryStatus: null, errorCode: null, errorMessage: null,
        replyTo: null, createdAt: new Date().toISOString(),
      });
      await notePromise;
    });

    expect(result.current.thread?.id).toBe('cnt-002');
    expect(result.current.messages.length).toBe(cnt002MessageCount);
    expect(result.current.messages.some((m) => m.id === 'msg-stale-note')).toBe(false);
    spy.mockRestore();
  });

  // F12 (round-3 codex triage) - a WS message that lands for the NEW contact
  // WHILE its own initial `listMessages` fetch is still in flight must
  // survive that fetch resolving, not be silently wiped by a blind overwrite.
  it('F12: a WS message landing during the initial fetch is merged, not dropped', async () => {
    const { mockConversationService } = await import('@/services/conversation-service.mock');

    const { result, rerender } = renderHook(({ id }: { id: string }) => useMessages(id), {
      initialProps: { id: 'cnt-001' },
    });
    await waitFor(() => expect(result.current.thread?.id).toBe('cnt-001'));

    let resolveList!: (m: import('@/types/omnichannel').ConversationMessage[]) => void;
    const pendingList = new Promise<import('@/types/omnichannel').ConversationMessage[]>((resolve) => {
      resolveList = resolve;
    });
    const listSpy = vi.spyOn(mockConversationService, 'listMessages').mockReturnValue(pendingList);

    // Switch to cnt-002 (same workspace as cnt-001 - the socket subscription
    // never tears down across the switch) - its own `listMessages` fetch is
    // now stuck pending.
    rerender({ id: 'cnt-002' });

    // A WS message for cnt-002 arrives WHILE the fetch above is still in flight.
    act(() => __mockSimulateInbound('wsp-001', 'cnt-002'));
    await waitFor(() => expect(result.current.messages.length).toBe(1));
    const liveMessageId = result.current.messages[0].id;

    // NOW the slow REST snapshot resolves (an empty history, e.g. a brand
    // new contact) - it must be MERGED with the live message above, not
    // overwritten away. `getThread` carries its OWN real ~150ms mock delay
    // (`Promise.all` waits for both, and `onEvent` ALSO calls `setThread` off
    // the inbound event above, so "thread === cnt-002" alone isn't proof the
    // fetch's `.then()` ran) - wait out the real delay directly.
    act(() => resolveList([]));
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 300));
    });

    expect(result.current.messages.some((m) => m.id === liveMessageId)).toBe(true);
    listSpy.mockRestore();
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
