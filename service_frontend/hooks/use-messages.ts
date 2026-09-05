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
  PatchContactInput,
  SendContactsInput,
  SendInteractiveInput,
  SendLocationInput,
  SendMediaInput,
  SendMessageInput,
  SendTemplateInput,
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
  /** Send an approved template (BODY/header/button vars + optional header media). */
  sendTemplate: (input: SendTemplateInput) => Promise<boolean>;
  sendMedia: (input: SendMediaInput) => Promise<boolean>;
  sendInteractive: (input: SendInteractiveInput) => Promise<boolean>;
  sendLocation: (input: SendLocationInput) => Promise<boolean>;
  sendContacts: (input: SendContactsInput) => Promise<boolean>;
  /** React to a message by its id (empty emoji removes the agent's reaction). */
  react: (messageId: string, emoji: string) => Promise<boolean>;
  addNote: (body: string) => Promise<boolean>;
  assign: (userId: string | null) => Promise<void>;
  assignToMe: () => Promise<void>;
  setStatus: (status: ThreadStatus) => Promise<void>;
  setPriority: (priority: ThreadPriority) => Promise<void>;
  /** Plan 25 - system fields + typed custom fields + tag replace-set. Throws
   *  (ApiError, 422 fieldErrors) on failure - the Details form maps errors. */
  patchContact: (patch: PatchContactInput) => Promise<ConversationThread>;
  /** Plan 25 - move the lifecycle stage. Throws (ApiError, 409) on a
   *  no-longer-fireable move (a stale picker option). */
  moveLifecycle: (toStatusId: string) => Promise<ConversationThread>;
}

export function useMessages(contactId: string | null | undefined): UseMessagesResult {
  const [thread, setThread] = useState<ConversationThread | null>(null);
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isSending, setIsSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const fetchSeq = useRef(0);
  // F1: the currently-selected contact, as a ref so async setters below can
  // tell a STALE response (fired for the PREVIOUS contactId, resolving after
  // the user already switched threads) from a current one - without this,
  // e.g. a slow `patchContact` response for contact A can land after the
  // user selected contact B and overwrite B's just-loaded thread with A's.
  const activeContactIdRef = useRef(contactId);
  useEffect(() => {
    activeContactIdRef.current = contactId;
  }, [contactId]);

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
      } else if (
        event.type === 'message.reaction' &&
        event.contactId === contactId &&
        // An AGENT reaction is applied optimistically by the acting client - its
        // own WS echo would race that update (a late add re-applying after a
        // remove), so only CONTACT reactions update live here. Cross-agent live
        // reaction sync is a follow-up; another agent's reaction shows on reload.
        event.reactorType === 'CONTACT'
      ) {
        setMessages((prev) =>
          prev.map((m) => {
            if (m.id !== event.targetMessageId) return m;
            const others = m.reactions.filter((r) => r.reactorType !== 'CONTACT');
            return {
              ...m,
              reactions: event.removed
                ? others
                : [...others, { emoji: event.emoji, reactorType: 'CONTACT', reactor: 'CONTACT' }],
            };
          }),
        );
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
      // success or flag it FAILED on error. (Send no longer blocks the input -
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
        mediaUrl: null, mediaMime: null, mediaFilename: null, mediaSize: null, voice: false, payload: null,
        reactions: [],
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

  const sendTemplate = useCallback(
    async (input: SendTemplateInput): Promise<boolean> => {
      if (!contactId) return false;
      setSendError(null);
      setIsSending(true);
      try {
        const created = await conversationService.sendTemplate(contactId, input);
        setMessages((prev) => (prev.some((m) => m.id === created.id) ? prev : [...prev, created]));
        return true;
      } catch (e: unknown) {
        setSendError(e instanceof Error ? e.message : 'Could not send the template');
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
      // Optimistic bubble with a local preview (object URL - useMediaBlob uses
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
        voice: input.kind === 'voice', payload: null,
        reactions: [],
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

  // Structured sends (interactive/location/contacts) - append the created bubble.
  const runStructured = useCallback(
    async (fn: () => Promise<ConversationMessage>): Promise<boolean> => {
      if (!contactId) return false;
      setSendError(null);
      setIsSending(true);
      try {
        const created = await fn();
        setMessages((prev) => (prev.some((m) => m.id === created.id) ? prev : [...prev, created]));
        return true;
      } catch (e: unknown) {
        setSendError(e instanceof Error ? e.message : 'Could not send the message');
        return false;
      } finally {
        setIsSending(false);
      }
    },
    [contactId],
  );

  const sendInteractive = useCallback(
    (input: SendInteractiveInput) =>
      runStructured(() => conversationService.sendInteractive(contactId as string, input)),
    [contactId, runStructured],
  );
  const sendLocation = useCallback(
    (input: SendLocationInput) =>
      runStructured(() => conversationService.sendLocation(contactId as string, input)),
    [contactId, runStructured],
  );
  const sendContacts = useCallback(
    (input: SendContactsInput) =>
      runStructured(() => conversationService.sendContacts(contactId as string, input)),
    [contactId, runStructured],
  );

  const react = useCallback(
    async (messageId: string, emoji: string): Promise<boolean> => {
      if (!contactId) return false;
      try {
        const res = await conversationService.react(contactId, messageId, emoji);
        setMessages((prev) =>
          prev.map((m) => {
            if (m.id !== messageId) return m;
            const others = m.reactions.filter((r) => r.reactorType !== 'AGENT');
            return {
              ...m,
              reactions: res.removed
                ? others
                : [...others, { emoji: res.emoji, reactorType: 'AGENT' as const, reactor: 'AGENT' }],
            };
          }),
        );
        return true;
      } catch (e: unknown) {
        setSendError(e instanceof Error ? e.message : 'Could not react to the message');
        return false;
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

  // F1: only commit a resolved thread if `forContactId` is STILL the active
  // selection - a response that resolves after the user switched threads is
  // discarded (the caller still gets the resolved value back either way).
  const commitThreadIfActive = useCallback(
    (forContactId: string | null | undefined, updated: ConversationThread) => {
      if (activeContactIdRef.current === forContactId) {
        setThread(updated);
      }
      return updated;
    },
    [],
  );

  const assign = useCallback(
    async (userId: string | null) => {
      if (!contactId) return;
      commitThreadIfActive(contactId, await conversationService.assign(contactId, userId));
    },
    [contactId, commitThreadIfActive],
  );

  const assignToMe = useCallback(async () => {
    if (!contactId) return;
    commitThreadIfActive(contactId, await conversationService.assignToMe(contactId));
  }, [contactId, commitThreadIfActive]);

  const setStatus = useCallback(
    async (status: ThreadStatus) => {
      if (!contactId) return;
      commitThreadIfActive(contactId, await conversationService.setStatus(contactId, status));
    },
    [contactId, commitThreadIfActive],
  );

  const setPriority = useCallback(
    async (priority: ThreadPriority) => {
      if (!contactId) return;
      commitThreadIfActive(contactId, await conversationService.setPriority(contactId, priority));
    },
    [contactId, commitThreadIfActive],
  );

  const patchContact = useCallback(
    async (patch: PatchContactInput) => {
      if (!contactId) throw new Error('No conversation selected.');
      const updated = await conversationService.patchContact(contactId, patch);
      commitThreadIfActive(contactId, updated);
      return updated;
    },
    [contactId, commitThreadIfActive],
  );

  const moveLifecycle = useCallback(
    async (toStatusId: string) => {
      if (!contactId) throw new Error('No conversation selected.');
      const updated = await conversationService.moveLifecycle(contactId, toStatusId);
      commitThreadIfActive(contactId, updated);
      return updated;
    },
    [contactId, commitThreadIfActive],
  );

  return { thread, messages, isLoading, error, isSending, sendError, send, sendTemplate, sendMedia, sendInteractive, sendLocation, sendContacts, react, addNote, assign, assignToMe, setStatus, setPriority, patchContact, moveLifecycle };
}
