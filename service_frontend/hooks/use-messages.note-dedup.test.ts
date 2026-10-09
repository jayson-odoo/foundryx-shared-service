/**
 * Plan 27 S4 fix: `addNote`'s HTTP response and the backend's `message.created`
 * WS publish race (the backend publishes on the SAME commit the note write
 * lands on) - a note must render exactly once whichever arrives first,
 * matching `send`'s existing temp-bubble dedup pattern. Caught live via
 * agent-browser smoke (a duplicate SYSTEM bubble in both the Messages tab
 * and the merged Activities feed, AC-IVE-32).
 */
import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { mockConversationService } from '@/services/conversation-service.mock';
import type { ConversationMessage, ConversationSocketEvent } from '@/types/omnichannel';

vi.mock('@/services/conversation-service', () => ({
  conversationService: mockConversationService,
}));

import { useMessages } from './use-messages';

describe('useMessages addNote - WS-echo dedup', () => {
  it('renders the note exactly once when the WS push arrives before the HTTP response', async () => {
    const thread = await mockConversationService.getThread('cnt-001');

    let resolveNote: (m: ConversationMessage) => void = () => {};
    const notePromise = new Promise<ConversationMessage>((resolve) => {
      resolveNote = resolve;
    });
    const addNoteSpy = vi
      .spyOn(mockConversationService, 'addInternalNote')
      .mockReturnValue(notePromise);

    let capturedHandler: ((event: ConversationSocketEvent) => void) | null = null;
    const subscribeSpy = vi
      .spyOn(mockConversationService, 'subscribe')
      .mockImplementation((_workspaceId, handler) => {
        capturedHandler = handler;
        return () => {};
      });

    const { result } = renderHook(() => useMessages('cnt-001'));
    await waitFor(() => expect(result.current.thread).not.toBeNull());
    await waitFor(() => expect(capturedHandler).not.toBeNull());

    const before = result.current.messages.length;
    const noteMessage: ConversationMessage = {
      id: 'msg-note-race',
      contactId: 'cnt-001',
      channelId: null,
      senderType: 'SYSTEM',
      senderId: 'usr-demo',
      senderName: 'Demo User',
      messageType: 'TEXT',
      body: 'Following up on delivery ETA',
      mediaUrl: null,
      mediaMime: null,
      mediaFilename: null,
      mediaSize: null,
      voice: false,
      payload: null,
      reactions: [],
      externalMessageId: null,
      deliveryStatus: null,
      errorCode: null,
      errorMessage: null,
      replyTo: null,
      createdAt: new Date().toISOString(),
    };

    let addNotePromise!: Promise<boolean>;
    act(() => {
      addNotePromise = result.current.addNote(noteMessage.body ?? '');
    });

    // The WS push races ahead of the HTTP response resolving.
    act(() => {
      capturedHandler?.({ type: 'message.created', message: noteMessage, thread });
    });
    await act(async () => {
      resolveNote(noteMessage);
      await addNotePromise;
    });

    const matching = result.current.messages.filter((m) => m.id === 'msg-note-race');
    expect(matching).toHaveLength(1);
    expect(result.current.messages.length).toBe(before + 1);

    addNoteSpy.mockRestore();
    subscribeSpy.mockRestore();
  });
});
