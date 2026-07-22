'use client';

import { useEffect, useRef, useState } from 'react';
import { Bot, Loader2, Send, Sparkles, TriangleAlert, User } from 'lucide-react';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';
import type { GrillField, GrillMessage } from '@/types/grill';

export interface GrillChatProps {
  messages: GrillMessage[];
  fields: GrillField[];
  coveredFields: string[];
  missingFields: GrillField[];
  sending: boolean;
  generating: boolean;
  disabled: boolean;
  error: string | null;
  onSend: (message: string) => void;
  onGenerate: () => void;
}

/**
 * The grill conversation surface (AC-BI-29) — built from ui primitives (NOT the
 * omnichannel ConversationDrawer, which is WhatsApp-coupled). User turns are
 * right-aligned, assistant turns left-aligned; a thinking indicator shows while a
 * turn is in flight. The coverage bar + Generate button let the human end the
 * grill at any time (AC-BI-22). Single column — stacks cleanly at 375px.
 */
export function GrillChat({
  messages,
  fields,
  coveredFields,
  missingFields,
  sending,
  generating,
  disabled,
  error,
  onSend,
  onGenerate,
}: GrillChatProps) {
  const [draft, setDraft] = useState('');
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const node = scrollRef.current?.querySelector(
      '[data-radix-scroll-area-viewport]',
    ) as HTMLElement | null;
    if (node) node.scrollTop = node.scrollHeight;
  }, [messages, sending]);

  const captured = coveredFields.length;
  const total = fields.length;

  function submit() {
    const text = draft.trim();
    if (!text || sending || disabled) return;
    onSend(text);
    setDraft('');
  }

  return (
    <div className="flex flex-col gap-3">
      {/* Coverage indicator (AC-BI-22): N of M captured · missing … */}
      <div className="flex flex-col gap-1 rounded-lg border bg-muted/30 px-3 py-2 text-sm sm:flex-row sm:items-center sm:justify-between">
        <span className="font-medium">
          {captured} of {total} captured
        </span>
        {missingFields.length > 0 ? (
          <span className="text-muted-foreground">
            missing: {missingFields.map((f) => f.label).join(', ')}
          </span>
        ) : (
          <span className="text-green-600">All fields captured</span>
        )}
      </div>

      <ScrollArea
        ref={scrollRef}
        className="h-[46vh] min-h-[240px] rounded-lg border lg:h-[calc(100vh-26rem)]"
      >
        <div className="flex flex-col gap-4 p-4">
          {messages.length === 0 && !sending ? (
            <p className="py-10 text-center text-sm text-muted-foreground">
              No messages yet.
            </p>
          ) : null}

          {messages.map((m) => (
            <MessageRow key={m.id} message={m} />
          ))}

          {sending ? (
            <div className="flex items-start gap-2">
              <Avatar className="size-8 shrink-0">
                <AvatarFallback className="bg-primary/10 text-primary">
                  <Bot className="size-4" />
                </AvatarFallback>
              </Avatar>
              <div className="flex items-center gap-2 rounded-2xl rounded-tl-sm border bg-background px-3 py-2 text-sm text-muted-foreground">
                <Loader2 className="size-3.5 animate-spin" />
                Thinking…
              </div>
            </div>
          ) : null}
        </div>
      </ScrollArea>

      {error ? (
        <p className="flex items-start gap-1.5 text-sm text-destructive">
          <TriangleAlert className="mt-0.5 size-3.5 shrink-0" />
          <span>{error}</span>
        </p>
      ) : null}

      {/* Composer + Generate (always enabled — the human ends the grill). */}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
        <Textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          placeholder="Message the grill"
          disabled={disabled || sending}
          rows={2}
          className="flex-1 resize-none"
        />
        <div className="flex gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={submit}
            disabled={disabled || sending || !draft.trim()}
            className="flex-1 sm:flex-none"
          >
            <Send className="size-4" />
            Send
          </Button>
          <Button
            type="button"
            onClick={onGenerate}
            disabled={generating}
            className="flex-1 sm:flex-none"
          >
            {generating ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Sparkles className="size-4" />
            )}
            Generate
          </Button>
        </div>
      </div>
    </div>
  );
}

function MessageRow({ message }: { message: GrillMessage }) {
  const isUser = message.role === 'user';
  return (
    <div className={cn('flex items-start gap-2', isUser && 'flex-row-reverse')}>
      <Avatar className="size-8 shrink-0">
        <AvatarFallback
          className={cn(
            isUser ? 'bg-muted text-foreground' : 'bg-primary/10 text-primary',
          )}
        >
          {isUser ? <User className="size-4" /> : <Bot className="size-4" />}
        </AvatarFallback>
      </Avatar>
      <div
        className={cn(
          'max-w-[80%] whitespace-pre-wrap rounded-2xl border px-3 py-2 text-sm',
          isUser
            ? 'rounded-tr-sm bg-primary text-primary-foreground'
            : 'rounded-tl-sm bg-background',
        )}
      >
        {message.content}
      </div>
    </div>
  );
}
