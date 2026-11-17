'use client';

import { useEffect, useState } from 'react';
import { Check, Copy, LoaderCircleIcon } from 'lucide-react';
import { useCopyToClipboard } from '@/hooks/use-copy-to-clipboard';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';

export interface ShareLinkDialogProps {
  open: boolean;
  onClose: () => void;
  /** Fetches (mints on first use) the item's read-only share link. */
  loadUrl: () => Promise<string>;
}

/** Lane FEEDBACK-SUBSCRIBE: the item's read-only share link in a centred popup,
 * with the shared copy control (inline checkmark, AC-DLA-53). The link stays
 * visible and selectable, so it can be copied by hand when the browser
 * refuses the clipboard. Used by the board item page and the operator page. */
export function ShareLinkDialog({ open, onClose, loadUrl }: ShareLinkDialogProps) {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const { isCopied, error: copyError, copyToClipboard } = useCopyToClipboard();

  useEffect(() => {
    if (!open) return undefined;
    let active = true;
    setUrl(null);
    setError(null);
    loadUrl()
      .then((u) => active && setUrl(u))
      .catch(() => active && setError('Could not get the link.'));
    return () => {
      active = false;
    };
  }, [open, loadUrl, tick]);

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>Share link</DialogTitle>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-2">
          {url === null && !error && (
            <div className="flex justify-center py-2 text-muted-foreground">
              <LoaderCircleIcon className="size-5 animate-spin" />
            </div>
          )}
          {error && (
            <div className="flex items-center gap-2 text-sm text-destructive" role="alert">
              <span>{error}</span>
              <Button mode="link" size="sm" onClick={() => setTick((t) => t + 1)}>
                Try again
              </Button>
            </div>
          )}
          {url && (
            <div className="flex items-center gap-2">
              <Input
                readOnly
                aria-label="Share link"
                value={url}
                onFocus={(e) => e.currentTarget.select()}
                className="min-w-0 flex-1"
              />
              <Button
                variant="outline"
                mode="icon"
                aria-label={isCopied ? 'Copied' : 'Copy link'}
                onClick={() => copyToClipboard(url)}
              >
                {isCopied ? <Check className="size-4 text-primary" /> : <Copy className="size-4" />}
              </Button>
            </div>
          )}
          {copyError && <p className="text-sm text-destructive">Copy did not work. Select the link and copy it.</p>}
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
}
