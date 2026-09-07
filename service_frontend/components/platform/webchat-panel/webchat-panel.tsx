'use client';

import { useEffect, useState } from 'react';
import { MessageCircle, LoaderCircleIcon } from 'lucide-react';
import { overrideVars } from '@/lib/branding-tokens';
import { cn } from '@/lib/utils';
import { useVisitorChat } from '@/hooks/use-visitor-chat';
import type { WebchatPreChatValues, WebchatSessionResult } from '@/types/omnichannel';
import { Composer } from './composer';
import { PanelHeader } from './panel-header';
import { PreChatStep } from './prechat-step';
import { Transcript } from './transcript';

export interface WebchatPanelProps {
  widgetKey: string;
}

/** `true` only when this document is genuinely embedded as a child iframe
 *  (D-A7B-2) - drives whether the panel supplies its own responsive
 *  positioning (standalone) or simply fills its frame (the loader owns
 *  geometry, D-A7B-27). A cross-origin embed makes `window.top` throw on
 *  read in some browsers - guarded, not assumed absent. */
function isEmbedded(): boolean {
  if (typeof window === 'undefined') return false;
  try {
    return window.self !== window.top;
  } catch {
    return true;
  }
}

function postToHost(type: string, payload?: Record<string, unknown>): void {
  if (typeof window === 'undefined' || window.parent === window) return;
  window.parent.postMessage({ source: 'fx-webchat-panel', type, payload: payload ?? {} }, '*');
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

  useEffect(() => {
    postToHost('ready', { position });
  }, [position]);

  // Inbound loader -> panel messages (AC-WEB-45/46). Only a frame from the
  // embedding page itself, carrying the loader's own discriminant, is ever
  // acted on - a panel cannot pin a single expected host origin (it varies
  // per customer), so it validates the SOURCE window instead; `frame-
  // ancestors` (this route's own CSP) is what actually restricts which page
  // may embed it at all.
  useEffect(() => {
    function onMessage(event: MessageEvent) {
      if (typeof window === 'undefined' || event.source !== window.parent) return;
      const data = event.data as { source?: string; type?: string } | null;
      if (!data || data.source !== 'fx-webchat-loader') return;
      if (data.type === 'open') setIsOpen(true);
      else if (data.type === 'close') setIsOpen(false);
      // 'identify' (host identity assertion) is verified server-side in S5 -
      // there is no session field to carry it to yet, so it is intentionally
      // not read here.
    }
    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, []);

  const open = () => {
    setIsOpen(true);
    postToHost('opened', { position });
  };
  const close = () => {
    setIsOpen(false);
    postToHost('closed', { position });
  };

  // Fail closed on a dead session (unknown/off-list widget key) - no error
  // chrome on a public surface a stranger controls the embed of.
  if (chat.phase === 'error') return null;

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
        title={chat.session?.config.appearance.headerTitle ?? 'Chat'}
        subtitle={chat.session?.config.tenantName ?? undefined}
        onClose={close}
      />
      {chat.phase === 'loading' || !chat.session ? (
        <div className="flex grow items-center justify-center">
          <LoaderCircleIcon className="size-6 animate-spin text-muted-foreground" />
        </div>
      ) : chat.needsPreChat ? (
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
