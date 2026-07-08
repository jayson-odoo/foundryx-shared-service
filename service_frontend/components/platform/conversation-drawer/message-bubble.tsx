'use client';

/**
 * One message bubble (plan 05 §6): CONTACT left, AGENT right (primary-soft
 * FoundryX token), SYSTEM centered amber internal note. Agent bubbles carry
 * delivery ticks (✓ sent, ✓✓ delivered, ✓✓-info read, ⚠ failed + reason).
 * Right-click opens the WhatsApp-style context menu: Reply / Copy message /
 * Copy link to message.
 */
import { formatTime as formatTimeUtc } from '@/lib/datetime';
import { AlertTriangle, Check, CheckCheck, Copy, Link2, Reply, StickyNote } from 'lucide-react';

import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from '@/components/ui/context-menu';
import { cn } from '@/lib/utils';
import type { ConversationMessage, DeliveryStatus, ReplyRef } from '@/types/omnichannel';

import { MessageMedia, isMediaMessage } from './message-media';
import { MessageStructured, isStructuredMessage } from './message-structured';

export interface MessageBubbleProps {
  message: ConversationMessage;
  /** Contact display name — labels quoted CONTACT messages. */
  contactName?: string;
  /** Start a reply to this message (quoted composer). */
  onReply?: (message: ConversationMessage) => void;
  /** Render the message timestamp in the viewer's locale/tz. */
  formatTime?: (iso: string) => string;
  /** In-thread search term — occurrences in the body get <mark>ed. */
  highlight?: string;
  /** This bubble is the active search match (ring + scroll target). */
  isActiveMatch?: boolean;
}

/** Split `text` on case-insensitive `term` occurrences and <mark> them. */
export function HighlightedText({ text, term }: { text: string; term?: string }) {
  if (!term?.trim()) return <>{text}</>;
  const safe = term.trim().replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const parts = text.split(new RegExp(`(${safe})`, 'ig'));
  return (
    <>
      {parts.map((part, i) =>
        part.toLowerCase() === term.trim().toLowerCase() ? (
          <mark key={i} className="rounded-sm bg-amber-200 px-0.5 text-inherit dark:bg-amber-600/60">
            {part}
          </mark>
        ) : (
          part
        ),
      )}
    </>
  );
}

// Default = the shared UTC-pinned formatter in the browser tz; the drawer
// passes the session-bound formatter from useDatetime (plan sprint-2/05).
function defaultFormatTime(iso: string): string {
  return formatTimeUtc(iso);
}

export function DeliveryTicks({ status }: { status: DeliveryStatus | null }) {
  if (!status) return null;
  switch (status) {
    case 'SENT':
      return <Check data-testid="tick-sent" className="size-3.5 text-muted-foreground" />;
    case 'DELIVERED':
      return <CheckCheck data-testid="tick-delivered" className="size-3.5 text-muted-foreground" />;
    case 'READ':
      return <CheckCheck data-testid="tick-read" className="size-3.5 text-info" />;
    case 'FAILED':
      return <AlertTriangle data-testid="tick-failed" className="size-3.5 text-destructive" />;
  }
}

/** The quoted message strip inside a reply bubble. */
function QuotedBlock({ replyTo, contactName }: { replyTo: ReplyRef; contactName?: string }) {
  const author =
    replyTo.senderType === 'CONTACT' ? (contactName ?? 'Customer') : (replyTo.senderName ?? 'Agent');
  return (
    <div
      className="mb-1.5 rounded-md border-s-2 border-primary bg-background/60 px-2.5 py-1.5 text-xs"
      data-testid="quoted-block"
    >
      <div className="font-medium text-primary-accent">{author}</div>
      <p className="line-clamp-2 text-muted-foreground">{replyTo.body}</p>
    </div>
  );
}

async function copyText(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    // Clipboard unavailable (permissions/insecure context) — nothing to do.
  }
}

function messageLink(message: ConversationMessage): string {
  const url = new URL(window.location.href);
  url.searchParams.set('thread', message.contactId);
  url.searchParams.set('msg', message.id);
  return url.toString();
}

export function MessageBubble({
  message,
  contactName,
  onReply,
  formatTime = defaultFormatTime,
  highlight,
  isActiveMatch = false,
}: MessageBubbleProps) {
  const time = formatTime(message.createdAt);

  if (message.senderType === 'SYSTEM') {
    // Internal note — visible to agents only, never sent to the contact.
    return (
      <ContextMenu>
        <ContextMenuTrigger asChild>
          <div className="flex justify-center" data-testid="bubble-system">
            <div
              className={cn(
                'max-w-[80%] rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-900/50 dark:bg-amber-950/40 dark:text-amber-200',
                isActiveMatch && 'ring-2 ring-primary',
              )}
            >
              <div className="mb-0.5 flex items-center gap-1.5 text-xs font-medium">
                <StickyNote className="size-3.5" />
                Internal note · {message.senderName ?? 'Agent'} · {time}
              </div>
              <p className="whitespace-pre-wrap break-words">
                <HighlightedText text={message.body ?? ''} term={highlight} />
              </p>
            </div>
          </div>
        </ContextMenuTrigger>
        <ContextMenuContent>
          <ContextMenuItem onClick={() => void copyText(message.body ?? '')}>
            <Copy className="size-4" /> Copy note
          </ContextMenuItem>
        </ContextMenuContent>
      </ContextMenu>
    );
  }

  const isAgent = message.senderType === 'AGENT';
  const failed = message.deliveryStatus === 'FAILED';

  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>
        <div
          className={cn('flex', isAgent ? 'justify-end' : 'justify-start')}
          data-testid={isAgent ? 'bubble-agent' : 'bubble-contact'}
        >
          <div className="max-w-[75%]">
            <div
              className={cn(
                'rounded-2xl px-3.5 py-2 text-sm shadow-xs',
                isAgent
                  ? 'rounded-br-sm bg-primary-soft text-foreground'
                  : 'rounded-bl-sm bg-muted text-foreground',
                failed && 'opacity-80 ring-1 ring-destructive',
                isActiveMatch && 'ring-2 ring-primary',
              )}
            >
              {message.replyTo && <QuotedBlock replyTo={message.replyTo} contactName={contactName} />}
              {message.messageType === 'TEMPLATE' && (
                <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-primary-accent">
                  Template
                </div>
              )}
              {isStructuredMessage(message) ? (
                <MessageStructured message={message} />
              ) : isMediaMessage(message) ? (
                <div className="space-y-1">
                  <MessageMedia message={message} />
                  {message.body && (
                    <p className="whitespace-pre-wrap break-words">
                      <HighlightedText text={message.body} term={highlight} />
                    </p>
                  )}
                </div>
              ) : message.mediaUrl ? (
                <a href={message.mediaUrl} target="_blank" rel="noreferrer" className="underline underline-offset-2">
                  {message.body ?? 'Attachment'}
                </a>
              ) : (
                <p className="whitespace-pre-wrap break-words">
                  <HighlightedText text={message.body ?? ''} term={highlight} />
                </p>
              )}
              <div className="mt-0.5 flex items-center justify-end gap-1 text-[10px] text-muted-foreground">
                {time}
                {isAgent && <DeliveryTicks status={message.deliveryStatus} />}
              </div>
            </div>
            {failed && message.errorMessage && (
              <p className="mt-1 text-end text-xs text-destructive" data-testid="bubble-error">
                {message.errorMessage}
              </p>
            )}
          </div>
        </div>
      </ContextMenuTrigger>
      <ContextMenuContent data-testid="bubble-menu">
        {onReply && (
          <>
            <ContextMenuItem onClick={() => onReply(message)} data-testid="menu-reply">
              <Reply className="size-4" /> Reply
            </ContextMenuItem>
            <ContextMenuSeparator />
          </>
        )}
        <ContextMenuItem onClick={() => void copyText(message.body ?? '')} data-testid="menu-copy">
          <Copy className="size-4" /> Copy message
        </ContextMenuItem>
        <ContextMenuItem onClick={() => void copyText(messageLink(message))} data-testid="menu-copy-link">
          <Link2 className="size-4" /> Copy link to message
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  );
}
