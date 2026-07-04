'use client';

/**
 * Thread composer (plan 05 §6): free-form textarea inside the 24h CSW; once
 * the window closes the input locks and only an approved template can be sent
 * (mirrors the backend rule — decision 14). ★ inserts a workspace quick reply.
 */
import { useMemo, useState } from 'react';
import { Lock, Reply, Send, Star, X } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import type {
  ConversationMessage,
  QuickReply,
  SendMessageInput,
  WhatsAppTemplate,
} from '@/types/omnichannel';

export interface ComposerProps {
  /** CSW state, computed by the drawer from the thread (re-evaluated live). */
  windowOpen: boolean;
  templates: WhatsAppTemplate[];
  quickReplies: QuickReply[];
  isSending: boolean;
  sendError: string | null;
  onSend: (input: SendMessageInput) => Promise<boolean>;
  /** Note mode (Activities tab): SYSTEM bubble, no CSW involved. */
  mode?: 'message' | 'note';
  onAddNote?: (body: string) => Promise<boolean>;
  /** Active reply target (from the bubble context menu). */
  replyTo?: ConversationMessage | null;
  onCancelReply?: () => void;
}

function TemplateSendDialog({
  open,
  onOpenChange,
  templates,
  isSending,
  onSend,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  templates: WhatsAppTemplate[];
  isSending: boolean;
  onSend: (input: SendMessageInput) => Promise<boolean>;
}) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [variables, setVariables] = useState<string[]>([]);
  const selected = useMemo(() => templates.find((t) => t.id === selectedId) ?? null, [templates, selectedId]);

  const preview = selected
    ? selected.bodyText.replace(/\{\{(\d+)\}\}/g, (_, n) => variables[Number(n) - 1] || `{{${n}}}`)
    : '';
  // Note: not `variables.slice(...).every(...)` — an untouched form gives an
  // EMPTY array and [].every() is vacuously true. Index over variableCount.
  const ready =
    !!selected &&
    Array.from({ length: selected.variableCount }, (_, i) => variables[i]).every((v) => v?.trim());

  const submit = async () => {
    if (!selected) return;
    const ok = await onSend({
      messageType: 'TEMPLATE',
      templateId: selected.id,
      templateVariables: variables.slice(0, selected.variableCount),
    });
    if (ok) {
      onOpenChange(false);
      setSelectedId(null);
      setVariables([]);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Send a template</DialogTitle>
          <DialogDescription>
            The 24-hour window has closed — re-engage with an approved template.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Template</label>
            <Select
              value={selectedId ?? ''}
              onValueChange={(v) => {
                setSelectedId(v || null);
                setVariables([]);
              }}
            >
              <SelectTrigger data-testid="template-select">
                <SelectValue placeholder="Choose a template…" />
              </SelectTrigger>
              <SelectContent>
                {templates.map((t) => (
                  <SelectItem key={t.id} value={t.id}>
                    {t.name} ({t.language})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {selected && (
            <>
              {Array.from({ length: selected.variableCount }, (_, i) => (
                <div key={i} className="space-y-1.5">
                  <label className="text-sm text-muted-foreground">{`Variable {{${i + 1}}} *`}</label>
                  <Input
                    value={variables[i] ?? ''}
                    onChange={(e) =>
                      setVariables((prev) => {
                        const next = [...prev];
                        next[i] = e.target.value;
                        return next;
                      })
                    }
                    data-testid={`template-var-${i + 1}`}
                  />
                </div>
              ))}
              <div className="rounded-md bg-muted p-3 text-sm" data-testid="template-preview">
                {preview}
              </div>
            </>
          )}
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={!ready || isSending} data-testid="template-send">
            <Send className="size-4" /> Send template
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function Composer({
  windowOpen,
  templates,
  quickReplies,
  isSending,
  sendError,
  onSend,
  mode = 'message',
  onAddNote,
  replyTo = null,
  onCancelReply,
}: ComposerProps) {
  const [body, setBody] = useState('');
  const [quickOpen, setQuickOpen] = useState(false);
  const [templateOpen, setTemplateOpen] = useState(false);

  const isNote = mode === 'note';
  const locked = !isNote && !windowOpen;

  const submit = async () => {
    const text = body.trim();
    if (!text) return;
    const replyId = replyTo?.id;
    // Clear the composer immediately — the send is optimistic (the bubble shows
    // at once, marked FAILED by the hook if it errors), so the agent can keep
    // typing without waiting on the Graph round-trip.
    setBody('');
    onCancelReply?.();
    if (isNote) await onAddNote?.('' + text);
    else await onSend({ messageType: 'TEXT', body: text, replyToMessageId: replyId });
  };

  return (
    <div className="border-t bg-background p-3" data-testid="composer">
      {locked && (
        <div
          className="mb-2 flex items-center justify-between gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-900/50 dark:bg-amber-950/40 dark:text-amber-200"
          data-testid="csw-banner"
        >
          <span className="flex items-center gap-2">
            <Lock className="size-4 shrink-0" />
            The 24-hour window has closed — only an approved template can be sent.
          </span>
          <Button size="sm" variant="outline" onClick={() => setTemplateOpen(true)} data-testid="csw-pick-template">
            Choose template
          </Button>
        </div>
      )}
      {sendError && !locked && (
        <p className="mb-2 text-sm text-destructive" data-testid="send-error">
          {sendError}
        </p>
      )}
      {!isNote && replyTo && (
        <div
          className="mb-2 flex items-start gap-2 rounded-md border-s-2 border-primary bg-muted px-3 py-2 text-xs"
          data-testid="reply-strip"
        >
          <Reply className="mt-0.5 size-3.5 shrink-0 text-primary" />
          <div className="min-w-0 flex-1">
            <div className="font-medium text-primary-accent">
              Replying to {replyTo.senderType === 'CONTACT' ? 'customer' : (replyTo.senderName ?? 'agent')}
            </div>
            <p className="line-clamp-2 text-muted-foreground">{replyTo.body}</p>
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="size-6 shrink-0"
            onClick={onCancelReply}
            aria-label="Cancel reply"
            data-testid="reply-cancel"
          >
            <X className="size-3.5" />
          </Button>
        </div>
      )}
      <div className="flex items-end gap-2">
        <Textarea
          value={body}
          onChange={(e) => setBody(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              void submit();
            }
          }}
          placeholder={
            isNote
              ? 'Add an internal note (only your team sees this)…'
              : locked
                ? 'Free-form messaging is locked'
                : 'Type a message — Enter to send, Shift+Enter for a new line'
          }
          disabled={locked}
          className="min-h-[44px] max-h-40 flex-1 resize-none"
          data-testid={isNote ? 'note-input' : 'message-input'}
        />
        {!isNote && (
          <Popover open={quickOpen} onOpenChange={setQuickOpen}>
            <PopoverTrigger asChild>
              <Button
                variant="outline"
                size="icon"
                disabled={locked}
                aria-label="Quick replies"
                data-testid="quick-replies"
              >
                <Star className="size-4" />
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-80 p-0" align="end">
              <Command>
                <CommandInput placeholder="Search quick replies…" />
                <CommandList>
                  <CommandEmpty>No quick replies.</CommandEmpty>
                  <CommandGroup>
                    {quickReplies.map((qr) => (
                      <CommandItem
                        key={qr.id}
                        value={`${qr.shortcut ?? ''} ${qr.body}`}
                        onSelect={() => {
                          setBody((prev) => (prev ? `${prev} ${qr.body}` : qr.body));
                          setQuickOpen(false);
                        }}
                      >
                        <div>
                          {qr.shortcut && (
                            <div className="text-xs font-medium text-muted-foreground">{qr.shortcut}</div>
                          )}
                          <div className="line-clamp-2 text-sm">{qr.body}</div>
                        </div>
                      </CommandItem>
                    ))}
                  </CommandGroup>
                </CommandList>
              </Command>
            </PopoverContent>
          </Popover>
        )}
        <Button
          onClick={submit}
          disabled={locked || isSending || !body.trim()}
          size="icon"
          aria-label={isNote ? 'Add note' : 'Send message'}
          data-testid={isNote ? 'note-send' : 'message-send'}
        >
          <Send className="size-4" />
        </Button>
      </div>
      <TemplateSendDialog
        open={templateOpen}
        onOpenChange={setTemplateOpen}
        templates={templates}
        isSending={isSending}
        onSend={onSend}
      />
    </div>
  );
}
