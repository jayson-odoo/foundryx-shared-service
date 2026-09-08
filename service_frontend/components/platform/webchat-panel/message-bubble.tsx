import { formatTime } from '@/lib/datetime';
import { cn } from '@/lib/utils';
import type { VisitorMessage } from '@/types/omnichannel';
import { MessageText } from './message-text';

export interface MessageBubbleProps {
  message: VisitorMessage;
  onQuickReply: (title: string) => void;
}

/** One transcript bubble in the panel - visitor left, agent right. Media is
 *  rendered from the projection's own signed URL (AC-WEB-41); an image is
 *  shown inline, anything else is a plain download link. No sender name is
 *  ever shown beyond the CHANNEL's configured `agentName` (D-A7B-17). */
export function MessageBubble({ message, onQuickReply }: MessageBubbleProps) {
  const isAgent = message.direction === 'out';
  const time = formatTime(message.createdAt);
  const isImage = message.media?.mimeType?.startsWith('image/');

  return (
    <div className={cn('flex flex-col gap-1', isAgent ? 'items-start' : 'items-end')}>
      <div
        className={cn(
          'max-w-[85%] rounded-2xl px-3.5 py-2 text-sm shadow-xs',
          isAgent ? 'rounded-bl-sm bg-muted text-foreground' : 'rounded-br-sm bg-primary-soft text-foreground',
        )}
        data-testid={isAgent ? 'webchat-bubble-agent' : 'webchat-bubble-visitor'}
      >
        {message.media &&
          (isImage ? (
            // Signed, short-TTL cross-origin URL - next/image would need a
            // remote-pattern allowlist keyed to a per-message host.
            <img
              src={message.media.url}
              alt={message.media.name ?? 'Image'}
              className="mb-1 max-h-64 w-full rounded-lg object-contain"
            />
          ) : (
            <a
              href={message.media.url}
              target="_blank"
              rel="noreferrer noopener"
              className="mb-1 block underline underline-offset-2"
            >
              {message.media.name ?? 'Attachment'}
            </a>
          ))}
        {message.text && <MessageText text={message.text} />}
        <div className="mt-0.5 text-2xs text-muted-foreground">{time}</div>
      </div>
      {isAgent && message.quickReplies && message.quickReplies.length > 0 && (
        <div className="flex flex-wrap gap-1.5" data-testid="webchat-quick-replies">
          {message.quickReplies.map((reply) => (
            <button
              key={reply.id}
              type="button"
              onClick={() => onQuickReply(reply.title)}
              className="rounded-full border border-primary px-3 py-1.5 text-xs font-medium text-primary transition-colors hover:bg-primary-soft"
            >
              {reply.title}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
