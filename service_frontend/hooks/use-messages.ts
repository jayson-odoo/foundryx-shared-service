'use client';

/**
 * One open thread: messages + thread meta + composer actions (plan 05).
 * Live behaviour: `message.created` for this contact appends a bubble;
 * `message.status` flips the delivery tick; `contact.updated` patches meta
 * (assignment, status, CSW).
 */
import { useCallback, useEffect, useRef, useState } from 'react';

import { conversationService } from '@/services/conversation-service';
import type {
  ConversationMessage,
  ConversationSocketEvent,
  ConversationThread,
  SendMediaInput,
  SendMessageInput,
  ThreadPriority,
  ThreadStatus,
} from '@/types/omnichannel';

import { useConversationSocket } from './use-conversation-socket';

export interface UseMessagesResult {
  thread: ConversationThread | null;
  messages: ConversationMessage[];
  isLoading: boolean;
  error: string | null;
  /** True while a send is in flight. */
  isSending: boolean;
  /** Last send failure (CSW rejection etc). Cleared on the next attempt. */
  sendError: string | null;
  send: (input: SendMessageInput) => Promise<boolean>;
  sendMedia: (input: SendMediaInput) => Promise<boolean>;
  addNote: (body: string) => Promise<boolean>;
  assign: (userId: string | null) => Promise<void>;
  assignToMe: () => Promise<void>;
  setStatus: (status: ThreadStatus) => Promise<void>;
  setPriority: (priority: ThreadPriority) => Promise<void>;
}

export function useMessages(contactId: string | null | undefined): UseMessagesResult {
  const [thread, setThread] = useState<ConversationThread | null>(null);
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isSending, setIsSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const fetchSeq = useRef(0);

  useEffect(() => {
    if (!contactId) {
      setThread(null);
      setMessages([]);
      return;
    }
    const seq = ++fetchSeq.current;
    setIsLoading(true);
    setError(null);
    setSendError(null);
    Promise.all([conversationService.getThread(contactId), conversationService.listMessages(contactId)])
      .then(([t, msgs]) => {
        if (seq !== fetchSeq.current) return;
        setThread(t);
        setMessages(msgs);
      })
      .catch((e: unknown) => {
        if (seq !== fetchSeq.current) return;
        setError(e instanceof Error ? e.message : 'Could not load the conversation');
      })
      .finally(() => {
        if (seq === fetchSeq.current) setIsLoading(false);
      });
  }, [contactId]);

  const onEvent = useCallback(
    (event: ConversationSocketEvent) => {
      if (!contactId) return;
      if (event.type === 'message.created' && event.message.contactId === contactId) {
        setMessages((prev) =>
          prev.some((m) => m.id === event.message.id) ? prev : [...prev, event.message],
        );
        setThread(event.thread);
      } else if (event.type === 'message.status' && event.contactId === contactId) {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === event.messageId
              ? { ...m, deliveryStatus: event.deliveryStatus, errorMessage: event.errorMessage ?? m.errorMessage }
              : m,
          ),
        );
      } else if (event.type === 'contact.updated' && event.thread.id === contactId) {
        setThread(event.thread);
      }
    },
    [contactId],
  );
  useConversationSocket(thread?.workspaceId, onEvent);

  const send = useCallback(
    async (input: SendMessageInput): Promise<boolean> => {
      if (!contactId) return false;
      setSendError(null);

      // Optimistic bubble: render the agent's message the instant they hit
      // Enter, before the (synchronous) Graph round-trip. deliveryStatus=null
      // shows no tick (a "sending" look); we swap it for the real message on
      // success or flag it FAILED on error. (Send no longer blocks the input —
      // isSending only flips the composer's spinner, not the bubble.)
      const tempId = `temp-${crypto.randomUUID()}`;
      const optimistic: ConversationMessage = {
        id: tempId,
        contactId,
        channelId: null,
        senderType: 'AGENT',
        senderId: null,
        senderName: null,
        messageType: input.messageType,
        body: input.body ?? null,
        mediaUrl: null, mediaMime: null, mediaFilename: null, mediaSize: null, voice: false,
        externalMessageId: null,
        deliveryStatus: null,
        errorCode: null,
        errorMessage: null,
        replyTo: null,
        createdAt: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, optimistic]);
      setIsSending(true);
      try {
        const created = await conversationService.sendMessage(contactId, input);
        // Replace the temp bubble with the real message; if the WS echo already
        // delivered it (race), just drop the temp (dedupe by real id).
        setMessages((prev) => {
          const withoutTemp = prev.filter((m) => m.id !== tempId);
          return withoutTemp.some((m) => m.id === created.id)
            ? withoutTemp
            : [...withoutTemp, created];
        });
        return true;
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : 'Could not send the message';
        setSendError(msg);
        // Keep the bubble but mark it failed (CSW rejection, network, etc.).
        setMessages((prev) =>
          prev.map((m) =>
            m.id === tempId
              ? { ...m, deliveryStatus: 'FAILED', errorMessage: msg }
              : m,
          ),
        );
        return false;
      } finally {
        setIsSending(false);
      }
    },
    [contactId],
  );

  const sendMedia = useCallback(
    async (input: SendMediaInput): Promise<boolean> => {
      if (!contactId) return false;
      setSendError(null);
      // Optimistic bubble with a local preview (object URL — useMediaBlob uses
      // blob: URLs directly; the real message swaps in the backend path).
      const tempId = `temp-${crypto.randomUUID()}`;
      const previewUrl = URL.createObjectURL(input.file);
      const optimistic: ConversationMessage = {
        id: tempId,
        contactId,
        channelId: null,
        senderType: 'AGENT',
        senderId: null,
        senderName: null,
        messageType: input.kind.toUpperCase() as ConversationMessage['messageType'],
        body: input.caption ?? null,
        mediaUrl: previewUrl,
        mediaMime: input.file.type || null,
        mediaFilename: input.file.name,
        mediaSize: input.file.size,
        voice: input.kind === 'voice',
        externalMessageId: null,
        deliveryStatus: 'QUEUED',
        errorCode: null,
        errorMessage: null,
        replyTo: null,
        createdAt: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, optimistic]);
      setIsSending(true);
      try {
        const created = await conversationService.sendMedia(contactId, input);
        URL.revokeObjectURL(previewUrl);
        setMessages((prev) => {
          const withoutTemp = prev.filter((m) => m.id !== tempId);
          return withoutTemp.some((m) => m.id === created.id) ? withoutTemp : [...withoutTemp, created];
        });
        return true;
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : 'Could not send the attachment';
        setSendError(msg);
        setMessages((prev) =>
          prev.map((m) => (m.id === tempId ? { ...m, deliveryStatus: 'FAILED', errorMessage: msg } : m)),
        );
        return false;
      } finally {
        setIsSending(false);
      }
    },
    [contactId],
  );

  const addNote = useCallback(
    async (body: string): Promise<boolean> => {
      if (!contactId) return false;
      try {
        const note = await conversationService.addInternalNote(contactId, body);
        setMessages((prev) => [...prev, note]);
        return true;
      } catch (e: unknown) {
        setSendError(e instanceof Error ? e.message : 'Could not add the note');
        return false;
      }
    },
    [contactId],
  );

  const assign = useCallback(
    async (userId: string | null) => {
      if (!contactId) return;
      setThread(await conversationService.assign(contactId, userId));
    },
    [contactId],
  );

  const assignToMe = useCallback(async () => {
    if (!contactId) return;
    setThread(await conversationService.assignToMe(contactId));
  }, [contactId]);

  const setStatus = useCallback(
    async (status: ThreadStatus) => {
      if (!contactId) return;
      setThread(await conversationService.setStatus(contactId, status));
    },
    [contactId],
  );

  const setPriority = useCallback(
    async (priority: ThreadPriority) => {
      if (!contactId) return;
      setThread(await conversationService.setPriority(contactId, priority));
    },
    [contactId],
  );

  return { thread, messages, isLoading, error, isSending, sendError, send, sendMedia, addNote, assign, assignToMe, setStatus, setPriority };
}
