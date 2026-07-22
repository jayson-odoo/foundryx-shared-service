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
  /** The running per-field understood values (AC-BI-24c). */
  capturedSummary: Record<string, string>;
  missingFields: GrillField[];
  sending: boolean;
  generating: boolean;
  disabled: boolean;
  error: string | null;
  onSend: (message: string) => void;
}

/**
 * The grill conversation surface (AC-BI-29 / AC-BI-29c) — a bounded fixed-height
 * scroll-shell that fits ONE viewport: the captured-summary strip is pinned at
 * the top, the transcript scrolls internally, and the message input is pinned at
 * the bottom (no page scroll to reach it). Built from ui primitives (NOT the
 * omnichannel ConversationDrawer, which is WhatsApp-coupled).
 *
 * The shell reuses the omnichannel-inbox scroll discipline: a CSS grid whose
 * transcript row is `minmax(0,1fr)` (so it bounds instead of ballooning to
 * content), the whole grid is height-bounded to the viewport, and NO `flex-1`
 * sits on an unbounded parent. Generation fires ONLY from the natural-language
 * signal (AC-BI-29c) — there is no explicit Generate button; the app acts on the
 * model's `generateSignal` (D22-A). Single column — stacks cleanly at 375px.
 */
export function GrillChat({
  messages,
  fields,
  coveredFields,
  capturedSummary,
  missingFields,
  sending,
  generating,
  disabled,
  error,
  onSend,
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
    <div
      className={cn(
        // Bounded scroll-shell: transcript row = minmax(0,1fr) so it bounds and
        // scrolls internally; summary + composer keep their natural height. The
        // whole grid is height-bounded to the viewport so the input is always in
        // view without page scroll (verified at 375 + 1280).
        'grid min-h-[420px] gap-3',
        'h-[calc(100dvh-21rem)] lg:h-[calc(100vh-19rem)]',
        'grid-rows-[auto_auto_minmax(0,1fr)_auto]',
      )}
    >
      {/* Coverage indicator (AC-BI-22): N of M captured · missing … — pinned. */}
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

      {/* Running captured summary (AC-BI-24c): each target field + its current
          understood value. Capped so it never pushes the input off-screen on
          mobile — it scrolls within its own bound (values only — no how-to copy). */}
      <dl className="grid max-h-[26vh] gap-x-4 gap-y-2 overflow-y-auto rounded-lg border px-3 py-2.5 text-sm sm:grid-cols-2">
        {fields.map((f) => {
          const value = capturedSummary[f.key]?.trim();
          return (
            <div key={f.key} className="flex flex-col gap-0.5">
              <dt className="text-xs font-medium text-muted-foreground">{f.label}</dt>
              <dd
                className={cn(
                  'whitespace-pre-wrap break-words',
                  value ? 'text-foreground' : 'text-muted-foreground/60',
                )}
              >
                {value || '—'}
              </dd>
            </div>
          );
        })}
      </dl>

      {/* Transcript — the ONLY row that scrolls internally (bounded by 1fr). */}
      <ScrollArea ref={scrollRef} className="h-full min-h-0 rounded-lg border">
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

      {/* Composer (pinned) + any error / generating status stacked above it. */}
      <div className="flex flex-col gap-2">
        {error ? (
          <p className="flex items-start gap-1.5 text-sm text-destructive">
            <TriangleAlert className="mt-0.5 size-3.5 shrink-0" />
            <span>{error}</span>
          </p>
        ) : null}
        {generating ? (
          <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
            <Sparkles className="size-3.5 shrink-0 text-primary" />
            Generating the requirement…
          </p>
        ) : null}

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
          <Button
            type="button"
            onClick={submit}
            disabled={disabled || sending || !draft.trim()}
            className="sm:self-stretch"
          >
            <Send className="size-4" />
            Send
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
