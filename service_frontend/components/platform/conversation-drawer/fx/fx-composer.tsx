'use client';

/**
 * The reply box under the Foundryx UIUX switch (W1-CONV). Same sends, same
 * steps, same channel rules as today's composer; what changes:
 * - A blocked reply box says what it waits for in place (gap audit 7): a
 *   strip at its top with the one fix ("Choose template", "Connect channel")
 *   and the box greyed, "Free-form messages are locked".
 * - The typed text stays in the box until the send succeeds, so a failed send
 *   never loses what the agent wrote; it clears once the message is accepted.
 *   A second Enter while a send is still on its way does nothing.
 * - Attach, emoji and quick replies are quiet icon buttons with tooltips; the
 *   page's one red action is the conversation's Close, so Send is a quiet
 *   button. No press-and-hold before sending.
 */
import { useEffect, useRef, useState } from 'react';
import {
  Contact as ContactIcon,
  LayoutList,
  MapPin,
  Mic,
  Paperclip,
  Reply,
  Send,
  Smile,
  Star,
  Trash2,
} from 'lucide-react';

import { useHideMainAction } from '@/components/fx/actions/page-actions-context';
import { FxIconActionButton } from '@/components/fx/actions/icon-action';
import { FxBlockedArea } from '@/components/fx/banners/blocked-area';
import { FxTooltip } from '@/components/fx/fx-tooltip';
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
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Textarea } from '@/components/ui/textarea';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import { channelsListPath } from '@/app/(protected)/omnichannel/settings/channels/components/paths';
import { CHANNEL_CAPABILITIES } from '@/lib/channel-capabilities';
import { EMOJI_GROUPS } from '@/lib/emoji';
import { cn } from '@/lib/utils';
import type { MediaKind } from '@/types/omnichannel';

import {
  ATTACH_OPTIONS,
  PendingThumb,
  TemplateSendDialog,
  type ComposerProps,
  type PendingFile,
} from '../composer';
import {
  ContactsBuilderDialog,
  InteractiveBuilderDialog,
  LocationBuilderDialog,
} from '../structured-composer';

/** The strip's sentence for a closed window (pure, tested). */
export function fxWindowLine(locked: boolean, hasTemplates: boolean): string {
  if (!locked) return 'The standard messaging window has closed.';
  return hasTemplates
    ? 'The 24-hour window has closed. Only an approved template can be sent.'
    : 'The messaging window has closed.';
}

export function FxComposer({
  windowOpen,
  humanAgentWindowOpen = false,
  capabilities = CHANNEL_CAPABILITIES.WHATSAPP,
  visitorPresence = null,
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
  noChannel = false,
}: ComposerProps) {
  const [body, setBody] = useState('');
  const [quickOpen, setQuickOpen] = useState(false);
  const [templateOpen, setTemplateOpen] = useState(false);
  const [emojiOpen, setEmojiOpen] = useState(false);
  const [structured, setStructured] = useState<'interactive' | 'location' | 'contacts' | null>(null);
  const [pending, setPending] = useState<PendingFile[]>([]);
  const [recording, setRecording] = useState(false);
  const [recordSeconds, setRecordSeconds] = useState(0);
  // A text send on its way: a second Enter must not send the kept text twice.
  const textInFlight = useRef(false);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const attachKindRef = useRef<MediaKind>('image');
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);

  // A dialog opened from here is the page's one action meanwhile.
  useHideMainAction(templateOpen || structured !== null);

  const isNote = mode === 'note';
  const hasWindow = capabilities.reengageMode !== 'none';
  const extendedOpen = !windowOpen && humanAgentWindowOpen;
  const showNoChannel = !isNote && !!noChannel;
  const locked = showNoChannel || (!isNote && hasWindow && !windowOpen && !extendedOpen);
  const showWindowMarker = !showNoChannel && !isNote && hasWindow && !windowOpen;
  const showPresenceMarker = !isNote && !hasWindow;
  const canAttach = !isNote && !locked && !!onSendMedia;
  const availableAttachOptions = ATTACH_OPTIONS.filter((o) => capabilities.media[o.kind]);
  const canRecordVoice = canAttach && capabilities.media.voice;
  const canInteractive = !isNote && !locked && capabilities.quickReplies && !!onSendInteractive;
  const canLocation = !isNote && !locked && capabilities.location && !!onSendLocation;
  const canContacts = !isNote && !locked && capabilities.contacts && !!onSendContacts;
  const canStructured = canInteractive || canLocation || canContacts;

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
        kind === 'image' || kind === 'sticker' || kind === 'video' ? URL.createObjectURL(file) : undefined,
    }));
    setPending((prev) => [...prev, ...additions]);
    e.target.value = '';
  };

  const removePending = (id: string) => {
    setPending((prev) => {
      const item = prev.find((p) => p.id === id);
      if (item?.preview) URL.revokeObjectURL(item.preview);
      return prev.filter((p) => p.id !== id);
    });
  };

  const submit = async () => {
    // Attachments go first, each its own message, exactly as today.
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
    const sent = body;
    const text = sent.trim();
    if (!text || textInFlight.current) return;
    const replyId = replyTo?.id;
    textInFlight.current = true;
    try {
      const ok = isNote
        ? await onAddNote?.('' + text)
        : await onSend({ messageType: 'TEXT', body: text, replyToMessageId: replyId });
      if (ok) {
        // Clear only what was sent; anything typed meanwhile stays.
        setBody((current) => (current === sent ? '' : current));
        onCancelReply?.();
      }
    } finally {
      textInFlight.current = false;
    }
  };

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
      // Mic permission denied / unavailable - nothing to do.
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
    <div className="border-t border-(--fx-line) bg-(--fx-surface) p-3" data-testid="composer" data-fx-composer="">
      <input
        ref={fileInputRef}
        type="file"
        multiple
        hidden
        aria-label="Files to attach"
        onChange={onFilesChosen}
        data-testid="attach-input"
      />
      {showNoChannel && (
        <div className="mb-2" data-testid="no-channel-banner">
          <FxBlockedArea action={{ label: 'Connect channel', href: channelsListPath }}>
            No channel is connected to this workspace.
          </FxBlockedArea>
        </div>
      )}
      {showWindowMarker && (
        <div className="mb-2" data-testid="csw-banner">
          <FxBlockedArea
            action={
              locked && capabilities.template
                ? { label: 'Choose template', onClick: () => setTemplateOpen(true) }
                : undefined
            }
          >
            {fxWindowLine(locked, capabilities.template)}
          </FxBlockedArea>
        </div>
      )}
      {showPresenceMarker && (
        <div className="mb-2 flex items-center gap-2 text-xs text-(--fx-ink-3)" data-testid="presence-marker">
          <span
            className={cn('size-1.5 rounded-full', visitorPresence?.online ? 'bg-(--fx-ok)' : 'bg-(--fx-line-2)')}
            aria-hidden="true"
          />
          {visitorPresence?.label ?? 'Awaiting first message'}
        </div>
      )}
      {sendError && !locked && (
        <p role="alert" className="mb-2 text-sm text-(--fx-act)" data-testid="send-error">
          {sendError}
        </p>
      )}
      {!isNote && replyTo && (
        <div
          className="mb-2 flex items-start gap-2 rounded-(--fx-r-m) border-s-2 border-(--fx-link) bg-(--fx-surface-2) px-3 py-2 text-xs"
          data-testid="reply-strip"
        >
          <Reply className="mt-0.5 size-3.5 shrink-0 text-(--fx-link)" aria-hidden="true" />
          <div className="min-w-0 flex-1">
            <div className="font-semibold text-(--fx-link)">
              Replying to {replyTo.senderType === 'CONTACT' ? 'customer' : (replyTo.senderName ?? 'agent')}
            </div>
            <p className="line-clamp-2 text-(--fx-ink-2)">{replyTo.body}</p>
          </div>
          <FxIconActionButton
            label="Cancel reply"
            icon="close"
            mini
            onClick={onCancelReply}
            data-testid="reply-cancel"
            className="shrink-0 border-transparent bg-transparent"
          />
        </div>
      )}

      {hasPending && (
        <div className="mb-2 space-y-2" data-testid="attach-tray">
          {pending.map((item) => (
            <div key={item.id} className="flex items-center gap-2 rounded-(--fx-r-m) border border-(--fx-line) p-2">
              <PendingThumb item={item} />
              <div className="min-w-0 flex-1">
                <div className="truncate text-xs font-semibold">{item.file.name}</div>
                <Input
                  value={item.caption}
                  onChange={(e) =>
                    setPending((prev) => prev.map((p) => (p.id === item.id ? { ...p, caption: e.target.value } : p)))
                  }
                  placeholder="Caption"
                  aria-label={`Caption for ${item.file.name}`}
                  className="mt-1 h-8"
                  data-testid="attach-caption"
                />
              </div>
              <FxIconActionButton
                label={`Remove ${item.file.name}`}
                icon="trash"
                iconNode={<Trash2 className="size-4" />}
                mini
                onClick={() => removePending(item.id)}
                data-testid="attach-remove"
                className="shrink-0"
              />
            </div>
          ))}
        </div>
      )}

      {recording && (
        <div
          className="mb-2 flex items-center gap-3 rounded-(--fx-r-m) bg-(--fx-surface-2) px-3 py-2"
          data-testid="voice-recording"
        >
          <span className="flex size-3 animate-pulse rounded-full bg-(--fx-act)" aria-hidden="true" />
          <span className="flex-1 text-sm tabular-nums">
            Recording · {Math.floor(recordSeconds / 60)}:{String(recordSeconds % 60).padStart(2, '0')}
          </span>
          <Button variant="fx-text" size="sm" onClick={() => finishRecording(false)} data-testid="voice-cancel">
            Discard recording
          </Button>
          <Button variant="fx-quiet" size="sm" onClick={() => finishRecording(true)} data-testid="voice-send">
            <Send className="size-4" /> Send recording
          </Button>
        </div>
      )}

      <div className="flex items-end gap-1.5">
        {(canAttach || canStructured) && !recording && (
          <>
            <DropdownMenu>
              <FxTooltip label="Attach">
                <DropdownMenuTrigger asChild>
                  <FxIconActionButton
                    label="Attach"
                    icon="add"
                    iconNode={<Paperclip className="size-[18px]" />}
                    mini
                    data-testid="attach-menu"
                  />
                </DropdownMenuTrigger>
              </FxTooltip>
              <DropdownMenuContent align="start">
                {canAttach &&
                  availableAttachOptions.map(({ kind, label, Icon }) => (
                    <DropdownMenuItem key={kind} onSelect={() => openPicker(kind)} data-testid={`attach-${kind}`}>
                      <Icon className="size-4" /> {label}
                    </DropdownMenuItem>
                  ))}
                {canAttach && canStructured && <DropdownMenuSeparator />}
                {canInteractive && (
                  <DropdownMenuItem onSelect={() => setStructured('interactive')} data-testid="attach-interactive">
                    <LayoutList className="size-4" /> Interactive
                  </DropdownMenuItem>
                )}
                {canLocation && (
                  <DropdownMenuItem onSelect={() => setStructured('location')} data-testid="attach-location">
                    <MapPin className="size-4" /> Location
                  </DropdownMenuItem>
                )}
                {canContacts && (
                  <DropdownMenuItem onSelect={() => setStructured('contacts')} data-testid="attach-contact">
                    <ContactIcon className="size-4" /> Contact
                  </DropdownMenuItem>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
            <Popover open={emojiOpen} onOpenChange={setEmojiOpen}>
              <FxTooltip label="Emoji">
                <PopoverTrigger asChild>
                  <FxIconActionButton
                    label="Emoji"
                    icon="add"
                    iconNode={<Smile className="size-[18px]" />}
                    mini
                    data-testid="emoji-trigger"
                  />
                </PopoverTrigger>
              </FxTooltip>
              <PopoverContent className="w-72 p-2" align="start">
                <div className="max-h-64 space-y-2 overflow-y-auto">
                  {EMOJI_GROUPS.map((group) => (
                    <div key={group.label}>
                      <div className="px-1 pb-1 text-xs font-semibold text-(--fx-ink-3)">{group.label}</div>
                      <div className="grid grid-cols-8 gap-0.5">
                        {group.emojis.map((emoji, i) => (
                          <button
                            key={`${group.label}-${i}`}
                            type="button"
                            className={cn(PRESSED_CLASS, 'rounded p-1 text-lg hover:bg-(--fx-surface-2)')}
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
          placeholder={isNote ? 'Internal note' : locked ? 'Free-form messages are locked' : 'Message'}
          aria-label={isNote ? 'Internal note' : 'Message'}
          disabled={locked || recording}
          className="min-h-11 max-h-40 flex-1 resize-none"
          data-testid={isNote ? 'note-input' : 'message-input'}
        />

        {!isNote && (
          <Popover open={quickOpen} onOpenChange={setQuickOpen}>
            <FxTooltip label={locked ? 'Free-form messages are locked' : 'Quick replies'}>
              <PopoverTrigger asChild>
                <FxIconActionButton
                  label="Quick replies"
                  icon="add"
                  iconNode={<Star className="size-[18px]" />}
                  mini
                  disabled={locked}
                  data-testid="quick-replies"
                />
              </PopoverTrigger>
            </FxTooltip>
            <PopoverContent className="w-80 p-0" align="end">
              <Command>
                <CommandInput placeholder="Find a quick reply" />
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
                          {qr.shortcut && <div className="text-xs font-semibold text-(--fx-ink-3)">{qr.shortcut}</div>}
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

        {canRecordVoice && !recording && !hasPending && !body.trim() ? (
          <FxTooltip label="Record a voice message">
            <FxIconActionButton
              label="Record a voice message"
              icon="add"
              iconNode={<Mic className="size-[18px]" />}
              mini
              onClick={startRecording}
              data-testid="voice-record"
            />
          </FxTooltip>
        ) : (
          !recording && (
            <Button
              variant="fx-quiet"
              onClick={submit}
              disabled={sendDisabled}
              aria-label={isNote ? 'Add note' : 'Send message'}
              className="min-h-11 gap-1.5 px-4 disabled:opacity-45"
              data-testid={isNote ? 'note-send' : 'message-send'}
            >
              <Send className="size-4" aria-hidden="true" />
              <span className="max-sm:sr-only">{isNote ? 'Add note' : 'Send'}</span>
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
      {canInteractive && onSendInteractive && (
        <InteractiveBuilderDialog
          open={structured === 'interactive'}
          onOpenChange={(o) => setStructured(o ? 'interactive' : null)}
          isSending={isSending}
          onSubmit={onSendInteractive}
        />
      )}
      {canLocation && onSendLocation && (
        <LocationBuilderDialog
          open={structured === 'location'}
          onOpenChange={(o) => setStructured(o ? 'location' : null)}
          isSending={isSending}
          onSubmit={onSendLocation}
        />
      )}
      {canContacts && onSendContacts && (
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
