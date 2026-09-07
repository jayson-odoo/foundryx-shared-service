'use client';

import { useEffect, useState } from 'react';
import { MessageCircle } from 'lucide-react';
import { overrideVars } from '@/lib/branding-tokens';
import { cn } from '@/lib/utils';
import { isEmbedded, postToLoader, readLoaderFrame } from '@/lib/webchat-panel-bridge';
import { useVisitorChat } from '@/hooks/use-visitor-chat';
import type { WebchatPreChatValues, WebchatSessionResult } from '@/types/omnichannel';
import { Composer } from './composer';
import { PanelHeader } from './panel-header';
import { PreChatStep } from './prechat-step';
import { Transcript } from './transcript';

export interface WebchatPanelProps {
  widgetKey: string;
}

/** AC-WEB-52/53 - the online greeting, or the offline one once `online` is
 *  `false`. A channel that never set its own offline greeting (an empty
 *  string) falls back to the ONLINE greeting rather than showing a visitor
 *  a blank system line - the offline greeting is optional copy, not a
 *  required second field (foolproof-UI: never render nothing). */
function resolveGreeting(session: WebchatSessionResult): string {
  if (session.online) return session.config.greeting;
  return session.config.offlineGreeting || session.config.greeting;
}

/**
 * The web chat panel (plan 34 / A7b S4) - the Next.js public route the
 * loader's iframe loads (AC-WEB-44/47). Owns BOTH the closed launcher bubble
 * and the open chat window; toggling between them is what drives the
 * loader's resize via `postMessage` (AC-WEB-45).
 *
 * Amended 2026-09-09 (BL-SS-183): the panel renders NOTHING until the loader
 * hands it a session - so a panel URL opened directly, with no loader and
 * therefore no token, is a blank document: no launcher, no copy, no vendor
 * string, and no session ever started server-side.
 */
export function WebchatPanel({ widgetKey }: WebchatPanelProps) {
  const chat = useVisitorChat(widgetKey);
  const [isOpen, setIsOpen] = useState(false);
  const [embedded, setEmbedded] = useState(false);

  useEffect(() => {
    setEmbedded(isEmbedded());
  }, []);

  const position = chat.session?.config.appearance.position ?? 'right';

  // Brand tokens from the SESSION response (D-A7B-11) - applied to this
  // document's own root, the only DOM this frame owns.
  useEffect(() => {
    if (!chat.session) return;
    const root = document.documentElement;
    const tokens = chat.session.config.brandTokens;
    const vars = overrideVars({ light: tokens.light ?? {}, dark: tokens.dark ?? {} }, 'light');
    for (const [cssVar, value] of Object.entries(vars)) root.style.setProperty(cssVar, value);
  }, [chat.session]);

  // The loader learns the configured launcher side once the session it minted
  // has reached this document (`useVisitorChat` owns the `ready` handshake).
  useEffect(() => {
    postToLoader('resize', { position });
  }, [position]);

  // Inbound loader -> panel commands (AC-WEB-45/46). `readLoaderFrame`
  // validates the SOURCE window and the envelope - a panel cannot pin a
  // single expected host origin (it varies per customer), and
  // `frame-ancestors` (this route's own CSP) is what restricts which page may
  // embed it at all. The `session` frame is consumed by the hook.
  useEffect(() => {
    function onMessage(event: MessageEvent) {
      const frame = readLoaderFrame(event);
      if (!frame) return;
      if (frame.type === 'open') setIsOpen(true);
      else if (frame.type === 'close') setIsOpen(false);
    }
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, []);

  const open = () => {
    setIsOpen(true);
    postToLoader('opened', { position });
  };
  const close = () => {
    setIsOpen(false);
    postToLoader('closed', { position });
  };

  // No session = nothing to show. This is BOTH the pre-handshake instant of a
  // legitimate embed and the permanent state of a directly navigated panel.
  if (!chat.session) return null;

  if (!isOpen) {
    return (
      <div className="flex h-full w-full items-center justify-center">
        <button
          type="button"
          onClick={open}
          aria-label="Open chat"
          className="flex size-16 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-lg transition-transform hover:scale-105"
          data-testid="webchat-launcher"
        >
          <MessageCircle className="size-7" />
        </button>
      </div>
    );
  }

  return (
    <div
      className={cn(
        'flex h-full w-full flex-col overflow-hidden bg-background text-foreground',
        !embedded &&
          'fixed inset-0 sm:inset-auto sm:bottom-4 sm:h-[640px] sm:w-[400px] sm:rounded-2xl sm:border sm:border-border sm:shadow-xl',
        !embedded && (position === 'left' ? 'sm:left-4' : 'sm:right-4'),
      )}
      data-testid="webchat-panel"
    >
      <PanelHeader
        title={chat.session.config.appearance.headerTitle}
        subtitle={chat.session.config.tenantName ?? undefined}
        onClose={close}
      />
      {chat.needsPreChat ? (
        <PreChatStep
          toggles={chat.session.config.preChat}
          greeting={resolveGreeting(chat.session)}
          sending={chat.sending}
          error={chat.sendError}
          honeypot={chat.honeypot}
          onHoneypotChange={chat.setHoneypot}
          onSubmit={(text, values: WebchatPreChatValues) => void chat.send(text, values)}
        />
      ) : (
        <>
          <Transcript
            messages={chat.messages}
            greeting={resolveGreeting(chat.session)}
            onQuickReply={(title) => void chat.send(title)}
          />
          <Composer
            onSend={(text) => void chat.send(text)}
            sending={chat.sending}
            error={chat.sendError}
            honeypot={chat.honeypot}
            onHoneypotChange={chat.setHoneypot}
          />
        </>
      )}
    </div>
  );
}
