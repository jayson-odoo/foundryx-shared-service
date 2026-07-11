'use client';

/**
 * EmbedShell — the chromeless host for the omnichannel embed routes
 * (sprint-4/11 Slice 4). Runs the postMessage handshake (useEmbedSession),
 * bridges realtime events to coarse parent `activity` signals, posts `resize`
 * (inbox mode), and renders the reused conversation components once the session
 * is ready. No app shell, no sidebar/header, no login redirect.
 */
import { useCallback, useEffect, useRef } from 'react';
import { Loader2 } from 'lucide-react';

import { useConversationSocket } from '@/hooks/use-conversation-socket';
import type { ConversationSocketEvent } from '@/types/omnichannel';

import { EmbedInboxView } from './embed-inbox-view';
import { EmbedThreadView } from './embed-thread-view';
import { useEmbedSession, type EmbedStatus } from './use-embed-session';

// `thread` = compact single conversation (messages + composer only); `thread-full`
// = the same `thread:<contactId>` scope but the FULL conversation UI (contact
// header / assign / lifecycle). Both share the thread scope — compactness is a
// frontend render choice, not a token difference.
export type EmbedMode = 'thread' | 'thread-full' | 'inbox';

function EmbedStatusScreen({ status, error }: { status: EmbedStatus; error: string | null }) {
  return (
    <div className="flex h-full w-full items-center justify-center p-6 text-center">
      {status === 'error' ? (
        <p className="text-sm text-muted-foreground">{error ?? 'Could not start the conversation.'}</p>
      ) : (
        <Loader2 className="size-6 animate-spin text-muted-foreground" aria-label="Loading" />
      )}
    </div>
  );
}

export function EmbedShell({ mode }: { mode: EmbedMode }) {
  const { status, error, session, contactId, postActivity, postResize } = useEmbedSession();
  const rootRef = useRef<HTMLDivElement>(null);

  // Realtime → coarse parent activity (kind + contactId only; NEVER content).
  const onEvent = useCallback(
    (event: ConversationSocketEvent) => {
      if (event.type === 'message.created') {
        postActivity(
          event.message.senderType === 'CONTACT' ? 'message_received' : 'message_sent',
          event.message.contactId,
        );
      } else if (event.type === 'contact.updated') {
        postActivity('assigned', event.thread.id);
      }
    },
    [postActivity],
  );
  useConversationSocket(session?.workspace.id, onEvent);

  // Content-height → parent (inbox mode, so the host can size the iframe).
  useEffect(() => {
    if (mode !== 'inbox' || status !== 'ready') return;
    const el = rootRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(() => {
      postResize(Math.ceil(el.getBoundingClientRect().height));
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [mode, status, postResize]);

  const renderReady = () => {
    if (mode === 'thread' || mode === 'thread-full') {
      return <EmbedThreadView contactId={contactId} compact={mode === 'thread'} />;
    }
    return <EmbedInboxView workspaceId={session!.workspace.id} />;
  };

  return (
    <div
      ref={rootRef}
      className="flex h-screen min-h-0 w-full flex-col overflow-hidden bg-background text-foreground"
      data-testid="embed-shell"
    >
      {status === 'ready' ? renderReady() : <EmbedStatusScreen status={status} error={error} />}
    </div>
  );
}
