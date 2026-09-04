'use client';

/**
 * Thread composer (plan 05 §6 + plan 12 Slice 1): free-form textarea inside the
 * 24h CSW; once the window closes the input locks and only an approved template
 * sends (mirrors the backend rule). Rich composing: attach menu (photo/video/
 * audio/document/sticker) → multi-file preview tray with per-file captions, a
 * BUNDLED emoji picker (no CDN - CSP), a voice recorder (MediaRecorder → VOICE),
 * and ★ workspace quick replies.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Contact as ContactIcon,
  FileText,
  Image as ImageIcon,
  LayoutList,
  Lock,
  MapPin,
  Mic,
  Music,
  Paperclip,
  Reply,
  Send,
  Smile,
  Star,
  Sticker,
  Trash2,
  Video,
  X,
} from 'lucide-react';

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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { SearchSelect } from '@/components/platform/search-select';
import { Textarea } from '@/components/ui/textarea';
import { EMOJI_GROUPS } from '@/lib/emoji';
import {
  ContactsBuilderDialog,
  InteractiveBuilderDialog,
  LocationBuilderDialog,
} from './structured-composer';
import type {
  ConversationMessage,
  MediaKind,
  QuickReply,
  SendContactsInput,
  SendInteractiveInput,
  SendLocationInput,
  SendMediaInput,
  SendMessageInput,
  SendTemplateInput,
  TemplateHeaderFormat,
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
  /** Send an approved template (BODY/header/button vars + optional header media). */
  onSendTemplate: (input: SendTemplateInput) => Promise<boolean>;
  /** Send a media attachment (image/video/audio/voice/document/sticker). */
  onSendMedia?: (input: SendMediaInput) => Promise<boolean>;
  /** Structured sends (interactive/location/contacts) - plan 12 Slice 2. */
  onSendInteractive?: (input: SendInteractiveInput) => Promise<boolean>;
  onSendLocation?: (input: SendLocationInput) => Promise<boolean>;
  onSendContacts?: (input: SendContactsInput) => Promise<boolean>;
  /** Note mode (Activities tab): SYSTEM bubble, no CSW involved. */
  mode?: 'message' | 'note';
  onAddNote?: (body: string) => Promise<boolean>;
  /** Active reply target (from the bubble context menu). */
  replyTo?: ConversationMessage | null;
  onCancelReply?: () => void;
}

interface PendingFile {
  id: string;
  file: File;
  kind: MediaKind;
  caption: string;
  preview?: string;
}

const ATTACH_OPTIONS: { kind: MediaKind; label: string; accept: string; Icon: typeof ImageIcon }[] = [
  { kind: 'image', label: 'Photo', accept: 'image/png,image/jpeg', Icon: ImageIcon },
  { kind: 'video', label: 'Video', accept: 'video/mp4,video/3gpp', Icon: Video },
  { kind: 'audio', label: 'Audio', accept: 'audio/*', Icon: Music },
  { kind: 'document', label: 'Document', accept: '.pdf,.docx,.xlsx,.pptx,.txt', Icon: FileText },
  { kind: 'sticker', label: 'Sticker', accept: 'image/webp', Icon: Sticker },
];

/** File-picker accept string per media-header format. */
const HEADER_ACCEPT: Record<Exclude<TemplateHeaderFormat, 'TEXT'>, string> = {
  IMAGE: 'image/png,image/jpeg',
  VIDEO: 'video/mp4,video/3gpp',
  DOCUMENT: '.pdf,.docx,.xlsx,.pptx,.txt',
};

/** A row of positional {{n}} variable inputs. */
function VariableInputs({
  count,
  values,
  onChange,
  labelPrefix,
  testidPrefix,
}: {
  count: number;
  values: string[];
  onChange: (next: string[]) => void;
  labelPrefix: string;
  testidPrefix: string;
}) {
  return (
    <>
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="space-y-1.5">
          <label className="text-sm text-muted-foreground">{`${labelPrefix} {{${i + 1}}} *`}</label>
          <Input
            value={values[i] ?? ''}
            onChange={(e) => {
              const next = [...values];
              next[i] = e.target.value;
              onChange(next);
            }}
            data-testid={`${testidPrefix}-${i + 1}`}
          />
        </div>
      ))}
    </>
  );
}

function TemplateSendDialog({
  open,
  onOpenChange,
  templates,
  isSending,
  onSendTemplate,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  templates: WhatsAppTemplate[];
  isSending: boolean;
  onSendTemplate: (input: SendTemplateInput) => Promise<boolean>;
}) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [variables, setVariables] = useState<string[]>([]);
  const [headerVariables, setHeaderVariables] = useState<string[]>([]);
  const [buttonVariables, setButtonVariables] = useState<string[]>([]);
  const [headerFile, setHeaderFile] = useState<File | null>(null);
  const selected = useMemo(() => templates.find((t) => t.id === selectedId) ?? null, [templates, selectedId]);
  const mediaHeader = !!selected && !!selected.headerFormat && selected.headerFormat !== 'TEXT';

  const reset = () => {
    setSelectedId(null);
    setVariables([]);
    setHeaderVariables([]);
    setButtonVariables([]);
    setHeaderFile(null);
  };

  const preview = selected
    ? selected.bodyText.replace(/\{\{(\d+)\}\}/g, (_, n) => variables[Number(n) - 1] || `{{${n}}}`)
    : '';
  const filled = (n: number, vals: string[]) =>
    Array.from({ length: n }, (_, i) => vals[i]).every((v) => v?.trim());
  const ready =
    !!selected &&
    filled(selected.variableCount, variables) &&
    filled(selected.headerVariableCount, headerVariables) &&
    filled(selected.buttonVariableCount, buttonVariables) &&
    (!mediaHeader || !!headerFile);

  const submit = async () => {
    if (!selected || !ready) return;
    const ok = await onSendTemplate({
      templateId: selected.id,
      templateVariables: variables.slice(0, selected.variableCount),
      templateHeaderVariables:
        selected.headerVariableCount > 0 ? headerVariables.slice(0, selected.headerVariableCount) : undefined,
      templateButtonVariables:
        selected.buttonVariableCount > 0 ? buttonVariables.slice(0, selected.buttonVariableCount) : undefined,
      headerFile: mediaHeader ? headerFile : undefined,
    });
    if (ok) {
      onOpenChange(false);
      reset();
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Send a template</DialogTitle>
          <DialogDescription>
            The 24-hour window has closed - re-engage with an approved template.
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-4">
          <div className="space-y-1.5">
            <label className="text-sm font-medium">Template</label>
            <SearchSelect
              options={templates.map((t) => ({ value: t.id, label: `${t.name} (${t.language})` }))}
              value={selectedId}
              onChange={(v) => {
                setSelectedId(v || null);
                setVariables([]);
                setHeaderVariables([]);
                setButtonVariables([]);
                setHeaderFile(null);
              }}
              placeholder="Choose a template…"
              ariaLabel="Template"
              className="w-full"
            />
          </div>
          {selected && (
            <>
              {mediaHeader && (
                <div className="space-y-1.5">
                  <label className="text-sm text-muted-foreground">
                    {`${selected.headerFormat === 'IMAGE' ? 'Image' : selected.headerFormat === 'VIDEO' ? 'Video' : 'Document'} header *`}
                  </label>
                  <Input
                    type="file"
                    accept={HEADER_ACCEPT[selected.headerFormat as Exclude<TemplateHeaderFormat, 'TEXT'>]}
                    onChange={(e) => setHeaderFile(e.target.files?.[0] ?? null)}
                    data-testid="template-header-file"
                  />
                </div>
              )}
              {selected.headerVariableCount > 0 && (
                <VariableInputs
                  count={selected.headerVariableCount}
                  values={headerVariables}
                  onChange={setHeaderVariables}
                  labelPrefix="Header"
                  testidPrefix="template-header-var"
                />
              )}
              <VariableInputs
                count={selected.variableCount}
                values={variables}
                onChange={setVariables}
                labelPrefix="Variable"
                testidPrefix="template-var"
              />
              {selected.buttonVariableCount > 0 && (
                <VariableInputs
                  count={selected.buttonVariableCount}
                  values={buttonVariables}
                  onChange={setButtonVariables}
                  labelPrefix="Button URL"
                  testidPrefix="template-button-var"
                />
              )}
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

/** Preview thumbnail for a pending file. */
function PendingThumb({ item }: { item: PendingFile }) {
  if (item.preview && (item.kind === 'image' || item.kind === 'sticker')) {
    return <img src={item.preview} alt={item.file.name} className="size-12 rounded object-cover" />;
  }
  if (item.preview && item.kind === 'video') {
    return <video src={item.preview} className="size-12 rounded object-cover" />;
  }
  const Icon = item.kind === 'audio' ? Music : FileText;
  return (
    <span className="flex size-12 items-center justify-center rounded bg-muted text-muted-foreground">
      <Icon className="size-5" />
    </span>
  );
}

export function Composer({
  windowOpen,
  templates,
  quickReplies,
  isSending,
  sendError,
  onSend,
  onSendTemplate,
  onSendMedia,
  onSendInteractive,
  onSendLocation,
  onSendContacts,
  mode = 'message',
  onAddNote,
  replyTo = null,
  onCancelReply,
}: ComposerProps) {
  const [body, setBody] = useState('');
  const [quickOpen, setQuickOpen] = useState(false);
  const [templateOpen, setTemplateOpen] = useState(false);
  const [emojiOpen, setEmojiOpen] = useState(false);
  const [structured, setStructured] = useState<'interactive' | 'location' | 'contacts' | null>(null);
  const [pending, setPending] = useState<PendingFile[]>([]);
  const [recording, setRecording] = useState(false);
  const [recordSeconds, setRecordSeconds] = useState(0);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const attachKindRef = useRef<MediaKind>('image');
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);

  const isNote = mode === 'note';
  const locked = !isNote && !windowOpen;
  const canAttach = !isNote && !locked && !!onSendMedia;
  // Structured types are free-form → only offered inside the open 24h window.
  const canStructured =
    !isNote && !locked && !!(onSendInteractive || onSendLocation || onSendContacts);

  // Revoke object URLs + stop the mic on unmount so previews/streams don't leak.
  useEffect(() => {
    return () => {
      pending.forEach((p) => p.preview && URL.revokeObjectURL(p.preview));
      if (streamRef.current) streamRef.current.getTracks().forEach((t) => t.stop());
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const openPicker = (kind: MediaKind) => {
    attachKindRef.current = kind;
    const input = fileInputRef.current;
    if (!input) return;
    const opt = ATTACH_OPTIONS.find((o) => o.kind === kind);
    input.accept = opt?.accept ?? '';
    input.click();
  };

  const onFilesChosen = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    const kind = attachKindRef.current;
    const additions = files.map<PendingFile>((file) => ({
      id: crypto.randomUUID(),
      file,
      kind,
      caption: '',
      preview:
        kind === 'image' || kind === 'sticker' || kind === 'video'
          ? URL.createObjectURL(file)
          : undefined,
    }));
    setPending((prev) => [...prev, ...additions]);
    e.target.value = ''; // allow re-picking the same file
  };

  const removePending = (id: string) => {
    setPending((prev) => {
      const item = prev.find((p) => p.id === id);
      if (item?.preview) URL.revokeObjectURL(item.preview);
      return prev.filter((p) => p.id !== id);
    });
  };

  const submit = async () => {
    // Send any queued attachments first (each becomes its own message), then the
    // free-form text if present.
    if (pending.length && onSendMedia) {
      const replyId = replyTo?.id;
      const items = pending;
      setPending([]);
      onCancelReply?.();
      for (const item of items) {
        await onSendMedia({
          kind: item.kind,
          file: item.file,
          caption: item.caption.trim() || undefined,
          replyToMessageId: replyId,
        });
        if (item.preview) URL.revokeObjectURL(item.preview);
      }
    }
    const text = body.trim();
    if (!text) return;
    const replyId = replyTo?.id;
    setBody('');
    onCancelReply?.();
    if (isNote) await onAddNote?.('' + text);
    else await onSend({ messageType: 'TEXT', body: text, replyToMessageId: replyId });
  };

  // ── Voice recording (MediaRecorder → webm → VOICE) ────────────────────────
  const startRecording = async () => {
    if (!onSendMedia) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (ev) => {
        if (ev.data.size > 0) chunksRef.current.push(ev.data);
      };
      recorder.start();
      recorderRef.current = recorder;
      setRecording(true);
      setRecordSeconds(0);
    } catch {
      // Mic permission denied / unavailable - silently ignore (no how-to copy).
    }
  };

  const stopStream = () => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
  };

  const finishRecording = (send: boolean) => {
    const recorder = recorderRef.current;
    if (!recorder) return;
    recorder.onstop = () => {
      stopStream();
      if (send && chunksRef.current.length && onSendMedia) {
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || 'audio/webm' });
        const file = new File([blob], `voice-${Date.now()}.webm`, { type: blob.type });
        void onSendMedia({ kind: 'voice', file });
      }
      chunksRef.current = [];
    };
    recorder.stop();
    recorderRef.current = null;
    setRecording(false);
  };

  useEffect(() => {
    if (!recording) return;
    const t = setInterval(() => setRecordSeconds((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, [recording]);

  const hasPending = pending.length > 0;
  const sendDisabled = locked || isSending || (!body.trim() && !hasPending);

  return (
    <div className="border-t bg-background p-3" data-testid="composer">
      <input
        ref={fileInputRef}
        type="file"
        multiple
        hidden
        onChange={onFilesChosen}
        data-testid="attach-input"
      />
      {locked && (
        <div
          className="mb-2 flex items-center justify-between gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-900/50 dark:bg-amber-950/40 dark:text-amber-200"
          data-testid="csw-banner"
        >
          <span className="flex items-center gap-2">
            <Lock className="size-4 shrink-0" />
            The 24-hour window has closed - only an approved template can be sent.
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

      {/* Attachment preview tray (multi-file + per-file caption). */}
      {hasPending && (
        <div className="mb-2 space-y-2" data-testid="attach-tray">
          {pending.map((item) => (
            <div key={item.id} className="flex items-center gap-2 rounded-md border bg-muted/40 p-2">
              <PendingThumb item={item} />
              <div className="min-w-0 flex-1">
                <div className="truncate text-xs font-medium">{item.file.name}</div>
                <Input
                  value={item.caption}
                  onChange={(e) =>
                    setPending((prev) =>
                      prev.map((p) => (p.id === item.id ? { ...p, caption: e.target.value } : p)),
                    )
                  }
                  placeholder="Add a caption"
                  className="mt-1 h-8"
                  data-testid="attach-caption"
                />
              </div>
              <Button
                variant="ghost"
                size="icon"
                className="size-7 shrink-0"
                aria-label="Remove attachment"
                onClick={() => removePending(item.id)}
                data-testid="attach-remove"
              >
                <Trash2 className="size-4" />
              </Button>
            </div>
          ))}
        </div>
      )}

      {/* Voice recording bar. */}
      {recording && (
        <div className="mb-2 flex items-center gap-3 rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2" data-testid="voice-recording">
          <span className="flex size-3 animate-pulse rounded-full bg-destructive" />
          <span className="flex-1 text-sm tabular-nums">
            Recording · {Math.floor(recordSeconds / 60)}:{String(recordSeconds % 60).padStart(2, '0')}
          </span>
          <Button variant="ghost" size="sm" onClick={() => finishRecording(false)} data-testid="voice-cancel">
            Cancel
          </Button>
          <Button size="sm" onClick={() => finishRecording(true)} data-testid="voice-send">
            <Send className="size-4" /> Send
          </Button>
        </div>
      )}

      <div className="flex items-end gap-2">
        {(canAttach || canStructured) && !recording && (
          <>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="icon" aria-label="Attach" data-testid="attach-menu">
                  <Paperclip className="size-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start">
                {canAttach &&
                  ATTACH_OPTIONS.map(({ kind, label, Icon }) => (
                    <DropdownMenuItem
                      key={kind}
                      onSelect={() => openPicker(kind)}
                      data-testid={`attach-${kind}`}
                    >
                      <Icon className="size-4" /> {label}
                    </DropdownMenuItem>
                  ))}
                {canAttach && canStructured && <DropdownMenuSeparator />}
                {onSendInteractive && (
                  <DropdownMenuItem onSelect={() => setStructured('interactive')} data-testid="attach-interactive">
                    <LayoutList className="size-4" /> Interactive
                  </DropdownMenuItem>
                )}
                {onSendLocation && (
                  <DropdownMenuItem onSelect={() => setStructured('location')} data-testid="attach-location">
                    <MapPin className="size-4" /> Location
                  </DropdownMenuItem>
                )}
                {onSendContacts && (
                  <DropdownMenuItem onSelect={() => setStructured('contacts')} data-testid="attach-contact">
                    <ContactIcon className="size-4" /> Contact
                  </DropdownMenuItem>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
            <Popover open={emojiOpen} onOpenChange={setEmojiOpen}>
              <PopoverTrigger asChild>
                <Button variant="outline" size="icon" aria-label="Emoji" data-testid="emoji-trigger">
                  <Smile className="size-4" />
                </Button>
              </PopoverTrigger>
              <PopoverContent className="w-72 p-2" align="start">
                <div className="max-h-64 space-y-2 overflow-y-auto">
                  {EMOJI_GROUPS.map((group) => (
                    <div key={group.label}>
                      <div className="px-1 pb-1 text-2xs font-medium uppercase tracking-wide text-muted-foreground">
                        {group.label}
                      </div>
                      <div className="grid grid-cols-8 gap-0.5">
                        {group.emojis.map((emoji, i) => (
                          <button
                            key={`${group.label}-${i}`}
                            type="button"
                            className="rounded p-1 text-lg hover:bg-muted"
                            onClick={() => setBody((prev) => prev + emoji)}
                            data-testid="emoji-item"
                          >
                            {emoji}
                          </button>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </PopoverContent>
            </Popover>
          </>
        )}

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
                : 'Type a message - Enter to send, Shift+Enter for a new line'
          }
          disabled={locked || recording}
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

        {canAttach && !recording && !hasPending && !body.trim() ? (
          <Button
            variant="outline"
            size="icon"
            aria-label="Record voice"
            onClick={startRecording}
            data-testid="voice-record"
          >
            <Mic className="size-4" />
          </Button>
        ) : (
          !recording && (
            <Button
              onClick={submit}
              disabled={sendDisabled}
              size="icon"
              aria-label={isNote ? 'Add note' : 'Send message'}
              data-testid={isNote ? 'note-send' : 'message-send'}
            >
              <Send className="size-4" />
            </Button>
          )
        )}
      </div>

      <TemplateSendDialog
        open={templateOpen}
        onOpenChange={setTemplateOpen}
        templates={templates}
        isSending={isSending}
        onSendTemplate={onSendTemplate}
      />
      {onSendInteractive && (
        <InteractiveBuilderDialog
          open={structured === 'interactive'}
          onOpenChange={(o) => setStructured(o ? 'interactive' : null)}
          isSending={isSending}
          onSubmit={onSendInteractive}
        />
      )}
      {onSendLocation && (
        <LocationBuilderDialog
          open={structured === 'location'}
          onOpenChange={(o) => setStructured(o ? 'location' : null)}
          isSending={isSending}
          onSubmit={onSendLocation}
        />
      )}
      {onSendContacts && (
        <ContactsBuilderDialog
          open={structured === 'contacts'}
          onOpenChange={(o) => setStructured(o ? 'contacts' : null)}
          isSending={isSending}
          onSubmit={onSendContacts}
        />
      )}
    </div>
  );
}
