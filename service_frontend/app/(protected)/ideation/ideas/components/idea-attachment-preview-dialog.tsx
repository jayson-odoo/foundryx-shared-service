'use client';

import { Download } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import type { IdeaAttachment } from '@/types/ideation';

export interface IdeaAttachmentPreviewDialogProps {
  attachment: IdeaAttachment | null;
  onClose: () => void;
}

const isPdf = (name: string, url: string) =>
  name.toLowerCase().endsWith('.pdf') || url.toLowerCase().split('?')[0].endsWith('.pdf');

/**
 * Inline preview for an idea's captured media - mirrors the Documents drive
 * preview UX (Dialog + header with download), but keyed off the attachment's
 * already-durable ``url`` (sorento snapshotted the Respond CDN bytes to R2), so
 * there is no per-id signed-url fetch. Image/video/audio render inline; a PDF
 * iframes; anything else falls back to an open/download link.
 */
export function IdeaAttachmentPreviewDialog({
  attachment,
  onClose,
}: IdeaAttachmentPreviewDialogProps) {
  const a = attachment;
  const pdf = a ? isPdf(a.name, a.url) : false;

  return (
    <Dialog open={!!a} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-3xl gap-3">
        <DialogHeader className="flex-row items-center justify-between pr-8">
          <DialogTitle className="truncate">{a?.name}</DialogTitle>
          {a?.url && (
            <Button variant="outline" size="sm" asChild>
              <a href={a.url} target="_blank" rel="noopener noreferrer" download>
                <Download className="size-3.5" /> Download
              </a>
            </Button>
          )}
        </DialogHeader>

        <div className="flex min-h-[24rem] items-center justify-center overflow-hidden rounded-md border bg-muted/30">
          {!a?.url ? (
            <p className="p-6 text-sm text-muted-foreground">Preview unavailable.</p>
          ) : a.kind === 'image' ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={a.url} alt={a.name} className="max-h-[32rem] w-auto object-contain" />
          ) : a.kind === 'video' ? (
            <video src={a.url} controls className="max-h-[32rem] w-auto" />
          ) : a.kind === 'audio' ? (
            <audio src={a.url} controls className="w-full px-6" />
          ) : pdf ? (
            <iframe title={a.name} src={a.url} className="h-[32rem] w-full border-0" />
          ) : (
            <div className="flex flex-col items-center gap-3 p-6 text-center">
              <p className="text-sm text-muted-foreground">
                This file type can&apos;t be previewed inline.
              </p>
              <Button variant="outline" size="sm" asChild>
                <a href={a.url} target="_blank" rel="noopener noreferrer">
                  Open in new tab
                </a>
              </Button>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
