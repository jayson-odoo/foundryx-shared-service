'use client';

/**
 * Inline media renderer for a message bubble (plan 12 AC-12-07): image (click →
 * lightbox), video, audio, voice-note player, document card, sticker. Bytes are
 * fetched as an authed blob → object URL (never `<img src>` with a Bearer).
 */
import { useState } from 'react';
import { Download, FileText, ImageOff, Mic } from 'lucide-react';

import { Dialog, DialogContent } from '@/components/ui/dialog';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import { cn } from '@/lib/utils';
import { Skeleton } from '@/components/ui/skeleton';
import { useMediaBlob } from '@/hooks/use-media-blob';
import type { ConversationMessage } from '@/types/omnichannel';

function formatSize(bytes: number | null): string {
  if (!bytes || bytes <= 0) return '';
  const units = ['B', 'KB', 'MB', 'GB'];
  let n = bytes;
  let i = 0;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i += 1;
  }
  return `${n.toFixed(n >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
}

function LoadFailed({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2 rounded-md bg-muted px-3 py-2 text-xs text-muted-foreground" data-testid="media-failed">
      <ImageOff className="size-4" /> {label}
    </div>
  );
}

export function MessageMedia({ message }: { message: ConversationMessage }) {
  const { url, isLoading, error } = useMediaBlob(message.mediaUrl);
  const [lightbox, setLightbox] = useState(false);
  const type = message.messageType;

  if (isLoading && !url) {
    return <Skeleton className="h-40 w-52 rounded-md" data-testid="media-loading" />;
  }
  if (error || !url) {
    return <LoadFailed label="Media unavailable" />;
  }

  if (type === 'STICKER') {
    return (
      <img
        src={url}
        alt="sticker"
        loading="lazy"
        className="size-32 object-contain"
        data-testid="media-sticker"
      />
    );
  }

  if (type === 'IMAGE') {
    return (
      <>
        <button
          type="button"
          onClick={() => setLightbox(true)}
          className={cn(PRESSED_CLASS, 'block overflow-hidden rounded-md')}
          data-testid="media-image"
        >
          <img
            src={url}
            alt={message.body ?? 'image'}
            loading="lazy"
            className="max-h-64 max-w-full rounded-md object-cover"
          />
        </button>
        <Dialog open={lightbox} onOpenChange={setLightbox}>
          <DialogContent className="max-w-3xl bg-transparent p-0 shadow-none">
            <img src={url} alt={message.body ?? 'image'} className="max-h-[85vh] w-full rounded-md object-contain" />
          </DialogContent>
        </Dialog>
      </>
    );
  }

  if (type === 'VIDEO') {
    return (
      <video src={url} controls className="max-h-64 max-w-full rounded-md" data-testid="media-video" />
    );
  }

  if (type === 'VOICE') {
    return (
      <div className="flex items-center gap-2" data-testid="media-voice">
        <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
          <Mic className="size-4" />
        </span>
        <audio src={url} controls className="h-9 max-w-[220px]" />
      </div>
    );
  }

  if (type === 'AUDIO') {
    return <audio src={url} controls className="h-9 max-w-[240px]" data-testid="media-audio" />;
  }

  // DOCUMENT (and any other media) → file card with download.
  const name = message.mediaFilename ?? 'Document';
  return (
    <a
      href={url}
      download={name}
      className="flex items-center gap-2.5 rounded-md border bg-background/60 px-3 py-2 text-sm hover:bg-background"
      data-testid="media-document"
    >
      <FileText className="size-5 shrink-0 text-primary" />
      <span className="min-w-0 flex-1">
        <span className="block truncate font-medium">{name}</span>
        {message.mediaSize ? (
          <span className="text-xs text-muted-foreground">{formatSize(message.mediaSize)}</span>
        ) : null}
      </span>
      <Download className="size-4 shrink-0 text-muted-foreground" />
    </a>
  );
}

export const MEDIA_MESSAGE_TYPES = ['IMAGE', 'VIDEO', 'AUDIO', 'VOICE', 'DOCUMENT', 'STICKER'] as const;

export function isMediaMessage(message: ConversationMessage): boolean {
  return (MEDIA_MESSAGE_TYPES as readonly string[]).includes(message.messageType);
}
