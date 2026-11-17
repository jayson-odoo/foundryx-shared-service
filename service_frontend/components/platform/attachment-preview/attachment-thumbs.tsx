'use client';

import { useEffect, useState } from 'react';
import { FileText, Film, Music } from 'lucide-react';
import { ClampedText } from '@/components/platform/clamped-text';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import { cn } from '@/lib/utils';
import type { IdeaAttachment } from '@/types/ideation';
import { IdeaAttachmentPreviewDialog } from './idea-attachment-preview-dialog';

export interface AttachmentThumbsProps {
  attachments: IdeaAttachment[];
  /** Fetch an uploaded file's bytes through the api-client (its serve route is
   * auth-gated, so a bare `src` would 401). */
  fetchContent?: (attachment: IdeaAttachment) => Promise<Blob>;
  className?: string;
}

function KindIcon({ kind }: { kind: IdeaAttachment['kind'] }) {
  const cls = 'size-6 text-muted-foreground';
  if (kind === 'video') return <Film className={cls} aria-hidden />;
  if (kind === 'audio') return <Music className={cls} aria-hidden />;
  return <FileText className={cls} aria-hidden />;
}

/** The square picture of an image; fetched as a blob when it is an upload. */
function ImageThumb({ attachment, fetchContent }: { attachment: IdeaAttachment; fetchContent?: AttachmentThumbsProps['fetchContent'] }) {
  const [src, setSrc] = useState<string | null>(attachment.contentPath ? null : attachment.url || null);
  useEffect(() => {
    if (!attachment.contentPath || !fetchContent) return;
    let active = true;
    let created: string | null = null;
    fetchContent(attachment)
      .then((blob) => {
        if (!active) return;
        created = URL.createObjectURL(blob);
        setSrc(created);
      })
      .catch(() => undefined);
    return () => {
      active = false;
      if (created) URL.revokeObjectURL(created);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attachment.id, attachment.contentPath]);
  if (!src) return <KindIcon kind="file" />;
  return <img src={src} alt="" className="size-full object-cover" />;
}

/**
 * A wrapping strip of small square thumbnails for uploaded files (an image shows
 * its picture, anything else an icon + name). Click opens the shared preview
 * dialog. Used on every surface that shows attachments (board, staff comments).
 */
export function AttachmentThumbs({ attachments, fetchContent, className }: AttachmentThumbsProps) {
  const [open, setOpen] = useState<IdeaAttachment | null>(null);
  if (attachments.length === 0) return null;
  return (
    <>
      <ul className={cn('flex flex-wrap gap-2', className)}>
        {attachments.map((a) => (
          <li key={a.id} className="w-20">
            <button
              type="button"
              aria-label={a.name}
              onClick={() => setOpen(a)}
              className={cn(
                PRESSED_CLASS,
                'flex size-20 items-center justify-center overflow-hidden rounded-md border bg-muted/30 hover:border-primary',
              )}
            >
              {a.kind === 'image' ? <ImageThumb attachment={a} fetchContent={fetchContent} /> : <KindIcon kind={a.kind} />}
            </button>
            <ClampedText text={a.name} lines={1} className="mt-1 text-2xs text-muted-foreground" />
          </li>
        ))}
      </ul>
      <IdeaAttachmentPreviewDialog attachment={open} onClose={() => setOpen(null)} fetchContent={fetchContent} />
    </>
  );
}
