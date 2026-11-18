'use client';

/**
 * A message bubble under the Foundryx UIUX switch (W1-CONV). Same content,
 * same right-click menu (react, reply, copy, copy link) as today; the look
 * moves to the fx tokens and an agent's message always says where it is:
 * Sending, Queued, Sent, Delivered, Read or Not sent (with the reason under
 * the bubble). The word is the icon's tooltip and its screen-reader name.
 */
import {
  AlertTriangle,
  Check,
  CheckCheck,
  Clock,
  Copy,
  Link2,
  Reply,
  SmilePlus,
  StickyNote,
  X,
} from 'lucide-react';
import type {
  ConversationMessage,
  DeliveryStatus,
  ReplyRef,
} from '@/types/omnichannel';
import { formatTime as formatTimeUtc } from '@/lib/datetime';
import { EMOJI_GROUPS } from '@/lib/emoji';
import { cn } from '@/lib/utils';
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuSub,
  ContextMenuSubContent,
  ContextMenuSubTrigger,
  ContextMenuTrigger,
} from '@/components/ui/context-menu';
import { FxTooltip } from '@/components/fx/fx-tooltip';
import {
  copyText,
  HighlightedText,
  messageLink,
  QUICK_EMOJIS,
  type MessageBubbleProps,
} from '../message-bubble';
import { isMediaMessage, MessageMedia } from '../message-media';
import { isStructuredMessage, MessageStructured } from '../message-structured';

/** What an agent's message is doing now, in words (pure, tested). `null`
 *  only means "Sending" for the composer's own optimistic bubble. */
export function fxDeliveryLabel(
  message: Pick<ConversationMessage, 'id' | 'deliveryStatus'>,
): string | null {
  const status: DeliveryStatus | null = message.deliveryStatus;
  switch (status) {
    case 'QUEUED':
      return 'Queued';
    case 'SENT':
      return 'Sent';
    case 'DELIVERED':
      return 'Delivered';
    case 'READ':
      return 'Read';
    case 'FAILED':
      return 'Not sent';
    default:
      return message.id.startsWith('temp-') ? 'Sending' : null;
  }
}

function FxDeliveryState({ message }: { message: ConversationMessage }) {
  const label = fxDeliveryLabel(message);
  if (!label) return null;
  const status = message.deliveryStatus;
  const icon =
    status === 'FAILED' ? (
      <AlertTriangle className="size-3.5 text-(--fx-act)" aria-hidden="true" />
    ) : status === 'READ' ? (
      <CheckCheck className="size-3.5 text-(--fx-link)" aria-hidden="true" />
    ) : status === 'DELIVERED' ? (
      <CheckCheck className="size-3.5" aria-hidden="true" />
    ) : status === 'SENT' ? (
      <Check className="size-3.5" aria-hidden="true" />
    ) : (
      <Clock className="size-3.5" aria-hidden="true" />
    );
  return (
    <FxTooltip label={label}>
      <span
        role="img"
        aria-label={label}
        data-testid="fx-delivery"
        data-fx-delivery={label}
        className="inline-flex"
      >
        {icon}
      </span>
    </FxTooltip>
  );
}

function FxQuotedBlock({
  replyTo,
  contactName,
}: {
  replyTo: ReplyRef;
  contactName?: string;
}) {
  const author =
    replyTo.senderType === 'CONTACT'
      ? (contactName ?? 'Customer')
      : (replyTo.senderName ?? 'Agent');
  return (
    <div
      className="mb-1.5 rounded-(--fx-r-s) border-s-2 border-(--fx-link) bg-(--fx-surface)/70 px-2.5 py-1.5 text-xs"
      data-testid="quoted-block"
    >
      <div className="font-semibold text-(--fx-link)">{author}</div>
      <p className="line-clamp-2 text-(--fx-ink-2)">{replyTo.body}</p>
    </div>
  );
}

function FxReactionChips({
  message,
  align,
}: {
  message: ConversationMessage;
  align: 'start' | 'end';
}) {
  if (message.reactions.length === 0) return null;
  const counts = message.reactions.reduce<Record<string, number>>((acc, r) => {
    acc[r.emoji] = (acc[r.emoji] ?? 0) + 1;
    return acc;
  }, {});
  return (
    <div
      className={cn(
        'mt-1 flex flex-wrap gap-1',
        align === 'end' ? 'justify-end' : 'justify-start',
      )}
      data-testid="reaction-chips"
    >
      {Object.entries(counts).map(([emoji, count]) => (
        <span
          key={emoji}
          className="inline-flex items-center gap-0.5 rounded-(--fx-r-pill) border border-(--fx-line) bg-(--fx-surface) px-1.5 py-0.5 text-xs"
        >
          <span>{emoji}</span>
          {count > 1 && <span className="text-(--fx-ink-3)">{count}</span>}
        </span>
      ))}
    </div>
  );
}

function defaultFormatTime(iso: string): string {
  return formatTimeUtc(iso);
}

export function FxMessageBubble({
  message,
  contactName,
  onReply,
  formatTime = defaultFormatTime,
  highlight,
  isActiveMatch = false,
  onReact,
}: MessageBubbleProps) {
  const time = formatTime(message.createdAt);
  const agentReacted = message.reactions.some((r) => r.reactorType === 'AGENT');

  if (message.senderType === 'SYSTEM') {
    return (
      <ContextMenu>
        <ContextMenuTrigger asChild>
          <div className="flex justify-center" data-testid="bubble-system">
            <div
              className={cn(
                'max-w-[80%] rounded-(--fx-r-m) bg-(--fx-warn-bg) px-3 py-2 text-sm text-(--fx-warn-ink)',
                isActiveMatch && 'ring-2 ring-(--fx-link)',
              )}
            >
              <div className="mb-0.5 flex items-center gap-1.5 text-xs font-semibold">
                <StickyNote className="size-3.5" aria-hidden="true" />
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
          <div className="max-w-[78%] min-w-0">
            <div
              className={cn(
                'rounded-(--fx-r-l) px-3.5 py-2 text-sm text-(--fx-ink)',
                isAgent
                  ? 'rounded-ee-(--fx-r-s) bg-(--fx-link-bg)'
                  : 'rounded-es-(--fx-r-s) border border-(--fx-line) bg-(--fx-surface)',
                failed && 'ring-1 ring-(--fx-act)',
                isActiveMatch && 'ring-2 ring-(--fx-link)',
              )}
            >
              {message.replyTo && (
                <FxQuotedBlock
                  replyTo={message.replyTo}
                  contactName={contactName}
                />
              )}
              {message.messageType === 'TEMPLATE' && (
                <div className="mb-1 text-xs font-semibold text-(--fx-ink-3)">
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
                <a
                  href={message.mediaUrl}
                  target="_blank"
                  rel="noreferrer"
                  className="text-(--fx-link) underline underline-offset-2"
                >
                  {message.body ?? 'Attachment'}
                </a>
              ) : (
                <p className="whitespace-pre-wrap break-words">
                  <HighlightedText text={message.body ?? ''} term={highlight} />
                </p>
              )}
              <div className="mt-0.5 flex items-center justify-end gap-1 text-xs tabular-nums text-(--fx-ink-3)">
                {time}
                {isAgent && <FxDeliveryState message={message} />}
              </div>
            </div>
            {failed && message.errorMessage && (
              <p
                className="mt-1 text-end text-xs text-(--fx-act)"
                data-testid="bubble-error"
              >
                {message.errorMessage}
              </p>
            )}
            <FxReactionChips
              message={message}
              align={isAgent ? 'end' : 'start'}
            />
          </div>
        </div>
      </ContextMenuTrigger>
      <ContextMenuContent data-testid="bubble-menu">
        {onReact && (
          <>
            <div
              className="flex items-center gap-0.5 px-1 py-0.5"
              data-testid="react-row"
            >
              {QUICK_EMOJIS.map((emoji) => (
                <ContextMenuItem
                  key={emoji}
                  onSelect={() => onReact(message, emoji)}
                  className="justify-center rounded px-1.5 py-1 text-base leading-none"
                  data-testid={`react-${emoji}`}
                  aria-label={`React ${emoji}`}
                >
                  {emoji}
                </ContextMenuItem>
              ))}
              <ContextMenuSub>
                <ContextMenuSubTrigger
                  className="justify-center rounded px-1.5 py-1 [&>svg:last-child]:hidden"
                  data-testid="react-more"
                  aria-label="More emojis"
                >
                  <SmilePlus className="size-4 text-(--fx-ink-2)" />
                </ContextMenuSubTrigger>
                <ContextMenuSubContent className="max-h-64 w-64 overflow-y-auto p-2">
                  {EMOJI_GROUPS.map((group) => (
                    <div key={group.label}>
                      <div className="px-1 pb-1 text-xs font-semibold text-(--fx-ink-3)">
                        {group.label}
                      </div>
                      <div className="grid grid-cols-8 gap-0.5 pb-1">
                        {group.emojis.map((emoji, i) => (
                          <ContextMenuItem
                            key={`${group.label}-${i}`}
                            onSelect={() => onReact(message, emoji)}
                            className="justify-center rounded p-1 text-lg leading-none"
                            data-testid="react-emoji-item"
                          >
                            {emoji}
                          </ContextMenuItem>
                        ))}
                      </div>
                    </div>
                  ))}
                </ContextMenuSubContent>
              </ContextMenuSub>
              {agentReacted && (
                <ContextMenuItem
                  onSelect={() => onReact(message, '')}
                  className="ms-0.5 justify-center rounded p-1 text-(--fx-ink-3)"
                  data-testid="react-remove"
                  aria-label="Remove reaction"
                >
                  <X className="size-3.5" />
                </ContextMenuItem>
              )}
            </div>
            <ContextMenuSeparator />
          </>
        )}
        {onReply && (
          <>
            <ContextMenuItem
              onClick={() => onReply(message)}
              data-testid="menu-reply"
            >
              <Reply className="size-4" /> Reply
            </ContextMenuItem>
            <ContextMenuSeparator />
          </>
        )}
        <ContextMenuItem
          onClick={() => void copyText(message.body ?? '')}
          data-testid="menu-copy"
        >
          <Copy className="size-4" /> Copy message
        </ContextMenuItem>
        <ContextMenuItem
          onClick={() => void copyText(messageLink(message))}
          data-testid="menu-copy-link"
        >
          <Link2 className="size-4" /> Copy link to message
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  );
}
