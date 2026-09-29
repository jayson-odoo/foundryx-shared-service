'use client';

import { useEffect, useState } from 'react';
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
  /** Fetch an UPLOADED attachment's bytes through the api-client (its serve
   * route is auth-gated, so a bare `src` would 401). Unused for a URL-backed
   * WhatsApp capture. */
  fetchContent?: (attachment: IdeaAttachment) => Promise<Blob>;
}

const isPdf = (name: string, url: string) =>
  name.toLowerCase().endsWith('.pdf') || url.toLowerCase().split('?')[0].endsWith('.pdf');

/**
 * Inline preview for an idea's captured media - mirrors the Documents drive
 * preview UX (Dialog + header with download), but keyed off the attachment's
 * already-durable ``url`` (sorento snapshotted the Respond CDN bytes to R2), so
 * there is no per-id signed-url fetch. Image/video/audio render inline; a PDF
 * iframes; anything else falls back to an open/download link. An uploaded
 * attachment (`contentPath`) is fetched as a blob and shown via an object URL,
 * revoked on close.
 */
export function IdeaAttachmentPreviewDialog({
  attachment,
  onClose,
  fetchContent,
}: IdeaAttachmentPreviewDialogProps) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const contentPath = attachment?.contentPath;

  useEffect(() => {
    if (!attachment || !contentPath || !fetchContent) return;
    let active = true;
    let created: string | null = null;
    fetchContent(attachment)
      .then((blob) => {
        if (!active) return;
        // Only when the response carried no type: a PDF by name gets its mime
        // so the browser previews it; anything else stays untyped.
        const typed =
          blob.type || !attachment.name.toLowerCase().endsWith('.pdf')
            ? blob
            : new Blob([blob], { type: 'application/pdf' });
        created = URL.createObjectURL(typed);
        setBlobUrl(created);
      })
      .catch(() => active && setBlobUrl(null));
    return () => {
      active = false;
      if (created) URL.revokeObjectURL(created);
      setBlobUrl(null);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attachment?.id, contentPath]);

  // Uploaded -> the blob object URL (null until fetched); captured -> its durable url.
  const a = attachment ? { ...attachment, url: contentPath ? (blobUrl ?? '') : attachment.url } : null;
  const pdf = a ? isPdf(a.name, a.url) : false;

  return (
    <Dialog open={!!a} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-3xl gap-3">
        <DialogHeader className="flex-row items-center justify-between pr-8">
          <DialogTitle className="truncate">{a?.name}</DialogTitle>
          {a?.url && (
            <Button variant="outline" size="sm" asChild>
              <a href={a.url} target="_blank" rel="noopener noreferrer" download={a.name}>
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
            <iframe title={a.name} src={a.url} sandbox="" className="h-[32rem] w-full border-0" />
          ) : (
            <div className="flex flex-col items-center gap-3 p-6 text-center">
              <p className="text-sm text-muted-foreground">
                This file type can&apos;t be previewed inline.
              </p>
              <Button variant="outline" size="sm" asChild>
                {contentPath ? (
                  <a href={a.url} download={a.name}>
                    Download
                  </a>
                ) : (
                  <a href={a.url} target="_blank" rel="noopener noreferrer">
                    Open in new tab
                  </a>
                )}
              </Button>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
