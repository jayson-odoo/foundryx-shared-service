'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '@/lib/api-client';
import { postToLoader, readLoaderFrame, sessionFromPayload } from '@/lib/webchat-panel-bridge';
import { webchatVisitorService } from '@/services/webchat-visitor-service';
import type {
  VisitorMessage,
  WebchatPreChatValues,
  WebchatSessionResult,
} from '@/types/omnichannel';

/** `waiting` = no session yet (the loader has not handed one over, or there
 *  is no loader at all - a directly navigated panel stays here forever and
 *  renders nothing). There is no error phase: the panel issues no request
 *  that can fail before it has a session. */
export type VisitorChatPhase = 'waiting' | 'ready';

export interface UseVisitorChatResult {
  phase: VisitorChatPhase;
  session: WebchatSessionResult | null;
  messages: VisitorMessage[];
  /** True only until the visitor's FIRST message of this session lands - the
   *  pre-chat step (AC-WEB-53) never resurfaces once a thread exists. */
  needsPreChat: boolean;
  sending: boolean;
  sendError: string | null;
  /** Bind to the always-rendered off-screen honeypot input (D-A7B-22-style
   *  form-engine precedent - a real visitor never fills it in). */
  honeypot: string;
  setHoneypot: (value: string) => void;
  send: (text: string, preChat?: WebchatPreChatValues) => Promise<void>;
}

const POLL_INTERVAL_MS = 4000;

function mergeMessages(existing: VisitorMessage[], incoming: VisitorMessage[]): VisitorMessage[] {
  if (incoming.length === 0) return existing;
  const byId = new Map(existing.map((m) => [m.id, m] as const));
  for (const message of incoming) byId.set(message.id, message);
  return Array.from(byId.values()).sort((a, b) => a.createdAt.localeCompare(b.createdAt));
}

/**
 * Visitor transcript + realtime for the web chat panel (plan 34 / A7b S4,
 * amended 2026-09-09 for BL-SS-183). Owns the send path and the
 * WebSocket-with-poll-fallback pair (D-A7B-16): the socket only opens once a
 * contact exists (S3 refuses the handshake otherwise, 4403), and the poll
 * timer runs whenever the socket is not `'open'` so no message is ever
 * missed regardless of which transport wins.
 *
 * It does NOT start the session and does NOT store the token: the LOADER
 * mints the session from the customer's own top-level page (the only place a
 * fetch carries the embedding website's `Origin`) and hands it over on the
 * `session` frame. Everything after that - history, poll, socket, send -
 * uses that Bearer exactly as before.
 */
export function useVisitorChat(widgetKey: string): UseVisitorChatResult {
  const [phase, setPhase] = useState<VisitorChatPhase>('waiting');
  const [session, setSession] = useState<WebchatSessionResult | null>(null);
  const [messages, setMessages] = useState<VisitorMessage[]>([]);
  const [needsPreChat, setNeedsPreChat] = useState(false);
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [honeypot, setHoneypot] = useState('');

  const sessionRef = useRef<WebchatSessionResult | null>(null);
  const messagesRef = useRef<VisitorMessage[]>([]);
  const hasContactRef = useRef(false);
  const unsubscribeRef = useRef<(() => void) | null>(null);
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const socketStatusRef = useRef<'connecting' | 'open' | 'closed'>('closed');

  useEffect(() => {
    sessionRef.current = session;
  }, [session]);
  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  const applyIncoming = useCallback((incoming: VisitorMessage[]) => {
    if (incoming.length === 0) return;
    setMessages((prev) => mergeMessages(prev, incoming));
  }, []);

  const stopPolling = useCallback(() => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  const pollOnce = useCallback(async () => {
    const current = sessionRef.current;
    if (!current) return;
    const last = messagesRef.current[messagesRef.current.length - 1];
    try {
      const page = await webchatVisitorService.listMessages(widgetKey, current.token, last?.id ?? null);
      applyIncoming(page.data);
    } catch {
      // A transient network blip - the next tick tries again. Never surfaces
      // an error state for a background poll (AC-WEB-49-style hygiene).
    }
  }, [applyIncoming, widgetKey]);

  const startPolling = useCallback(() => {
    if (pollTimerRef.current) return;
    pollTimerRef.current = setInterval(() => void pollOnce(), POLL_INTERVAL_MS);
  }, [pollOnce]);

  /** Takes the session explicitly rather than reading `sessionRef` - the
   *  adopt call site fires synchronously inside the loader-frame handler,
   *  BEFORE the `sessionRef` sync effect has run off the new `setSession`
   *  (effects run after render, not inside an event handler), so a ref read
   *  there would still see `null`. */
  const connectRealtime = useCallback(
    (target: WebchatSessionResult) => {
      if (unsubscribeRef.current) return;
      // Poll from the first tick (D-A7B-16) - a transport that never reports
      // a status at all (the mock, or a genuinely dead socket) must still
      // surface messages. `onStatus('open')` is what stops it once/if a real
      // socket connects; the mock never calls it, so polling simply stays on.
      startPolling();
      unsubscribeRef.current = webchatVisitorService.subscribe(
        target.workspaceId,
        target.token,
        (message) => applyIncoming([message]),
        (status) => {
          socketStatusRef.current = status;
          if (status === 'open') stopPolling();
          else startPolling();
        },
      );
    },
    [applyIncoming, startPolling, stopPolling],
  );

  const closeTransport = useCallback(() => {
    unsubscribeRef.current?.();
    unsubscribeRef.current = null;
    stopPolling();
  }, [stopPolling]);

  /** Adopt a session handed over by the loader. Called again on a re-mint
   *  (the loader's `identify()`), which is a DIFFERENT visitor - so the
   *  transcript and the transport are torn down and rebuilt, never merged. */
  const adoptSession = useCallback(
    (result: WebchatSessionResult) => {
      closeTransport();
      hasContactRef.current = result.messages.length > 0;
      sessionRef.current = result;
      messagesRef.current = result.messages;
      setSession(result);
      setMessages(result.messages);
      setNeedsPreChat(
        result.messages.length === 0 &&
          (result.config.preChat.askName ||
            result.config.preChat.askEmail ||
            result.config.preChat.askPhone),
      );
      setPhase('ready');
      if (hasContactRef.current) connectRealtime(result);
    },
    [closeTransport, connectRealtime],
  );

  // The session arrives from the LOADER (BL-SS-183), never from a fetch made
  // here. `ready` is posted from inside this effect, AFTER the listener is
  // attached, so the loader's reply can never race it. A panel with no
  // loader (direct navigation) simply never hears back and stays `waiting`.
  useEffect(() => {
    function onMessage(event: MessageEvent) {
      const frame = readLoaderFrame(event);
      if (!frame || frame.type !== 'session') return;
      const result = sessionFromPayload(frame.payload);
      if (result) adoptSession(result);
    }
    window.addEventListener('message', onMessage);
    postToLoader('ready');
    return () => {
      window.removeEventListener('message', onMessage);
      closeTransport();
    };
  }, [adoptSession, closeTransport]);

  const send = useCallback(
    async (text: string, preChat?: WebchatPreChatValues) => {
      const current = sessionRef.current;
      if (!current || !text.trim()) return;
      setSending(true);
      setSendError(null);
      try {
        const result = await webchatVisitorService.sendMessage(widgetKey, current.token, {
          text: text.trim(),
          preChat,
          hp: honeypot || undefined,
        });
        if (result) {
          applyIncoming([result]);
          setNeedsPreChat(false);
          if (!hasContactRef.current) {
            hasContactRef.current = true;
            connectRealtime(current);
          }
        }
      } catch (e) {
        if (e instanceof ApiError && e.status === 429) {
          setSendError('Too many messages - please slow down.');
        } else if (e instanceof ApiError && e.status === 422) {
          setSendError('That message could not be sent.');
        } else {
          setSendError('Could not send your message. Please try again.');
        }
      } finally {
        setSending(false);
      }
    },
    [applyIncoming, connectRealtime, honeypot, widgetKey],
  );

  return {
    phase,
    session,
    messages,
    needsPreChat,
    sending,
    sendError,
    honeypot,
    setHoneypot,
    send,
  };
}
