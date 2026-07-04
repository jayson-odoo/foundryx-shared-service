'use client';

import { useEffect, useState } from 'react';
import { Download, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { documentService } from '@/services/document-service';
import type { FileRow } from '@/types/documents';
import { canPreview, formatBytes } from './lib';

export interface PreviewDialogProps {
  file: FileRow | null;
  onClose: () => void;
  onDownload: (fileId: string) => void;
}

/**
 * Inline preview for images + PDFs. In production these stream from the
 * CSP-sandbox serve route; the iframe also carries `sandbox` defensively.
 */
export function PreviewDialog({ file, onClose, onDownload }: PreviewDialogProps) {
  const [url, setUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!file) {
      setUrl(null);
      return;
    }
    let cancelled = false;
    let revoke: string | null = null;
    setLoading(true);
    setError(false);
    documentService
      .previewUrl(file.id)
      .then((u) => {
        // Switched file / closed before this resolved: revoke immediately and
        // don't write stale state (else a leak + a flash of the old preview).
        if (cancelled) {
          if (u.startsWith('blob:')) URL.revokeObjectURL(u);
          return;
        }
        setUrl(u);
        if (u.startsWith('blob:')) revoke = u;
      })
      .catch(() => {
        if (!cancelled) setError(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
      if (revoke) URL.revokeObjectURL(revoke);
    };
  }, [file]);

  const isPdf = file ? file.name.toLowerCase().endsWith('.pdf') : false;

  return (
    <Dialog open={!!file} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-3xl gap-3">
        <DialogHeader className="flex-row items-center justify-between pr-8">
          <DialogTitle className="truncate">{file?.name}</DialogTitle>
          {file && (
            <Button variant="outline" size="sm" onClick={() => onDownload(file.id)}>
              <Download className="size-3.5" /> Download
            </Button>
          )}
        </DialogHeader>

        <div className="flex min-h-[24rem] items-center justify-center overflow-hidden rounded-md border bg-muted/30">
          {loading && <Loader2 className="size-6 animate-spin text-muted-foreground" />}
          {!loading && error && (
            <p className="p-6 text-sm text-muted-foreground">Preview unavailable.</p>
          )}
          {!loading && !error && url && file && canPreview(file) && (
            isPdf ? (
              <iframe
                title={file.name}
                src={url}
                className="h-[32rem] w-full border-0"
              />
            ) : (
              <img src={url} alt={file.name} className="max-h-[32rem] w-auto object-contain" />
            )
          )}
        </div>

        {file && (
          <p className="text-xs text-muted-foreground">
            {formatBytes(file.currentVersion.sizeBytes)}
            {file.versionCount > 1 ? ` · version ${file.versionCount}` : ''}
          </p>
        )}
      </DialogContent>
    </Dialog>
  );
}
