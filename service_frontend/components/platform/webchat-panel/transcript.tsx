'use client';

import { useEffect, useRef } from 'react';
import { ScrollArea } from '@/components/ui/scroll-area';
import type { VisitorMessage } from '@/types/omnichannel';
import { MessageBubble } from './message-bubble';
import { MessageText } from './message-text';

export interface TranscriptProps {
  messages: VisitorMessage[];
  /** The channel's own greeting (online) or offline greeting - rendered as
   *  the first, system-style line (AC-WEB-53). */
  greeting: string;
  onQuickReply: (title: string) => void;
}

/** The message history, oldest to newest, auto-scrolled to the latest
 *  message on arrival. */
export function Transcript({ messages, greeting, onQuickReply }: TranscriptProps) {
  const viewportRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = viewportRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages.length]);

  return (
    <ScrollArea className="min-h-0 grow" viewportRef={viewportRef}>
      <div className="flex flex-col gap-3 px-4 py-4" data-testid="webchat-transcript">
        <div className="max-w-[85%] rounded-2xl rounded-bl-sm bg-muted px-3.5 py-2 text-sm text-foreground shadow-xs">
          <MessageText text={greeting} />
        </div>
        {messages.map((message) => (
          <MessageBubble key={message.id} message={message} onQuickReply={onQuickReply} />
        ))}
      </div>
    </ScrollArea>
  );
}
