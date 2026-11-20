'use client';

import * as React from 'react';
import { copyText } from '@/lib/clipboard';

export function useCopyToClipboard({
  timeout = 2000,
  onCopy,
}: {
  timeout?: number;
  onCopy?: () => void;
} = {}) {
  const [isCopied, setIsCopied] = React.useState(false);
  const [error, setError] = React.useState(false);

  const done = (ok: boolean) => {
    if (ok) {
      setIsCopied(true);
      if (onCopy) onCopy();
      setTimeout(() => setIsCopied(false), timeout);
      return;
    }
    // T7 carry-over C2: a refused copy (denied permission, no secure
    // context, etc.) is surfaced inline beside the control, never a toast.
    setError(true);
    setTimeout(() => setError(false), timeout);
  };

  const copyToClipboard = (value: string) => {
    if (typeof window === 'undefined' || !value) return;
    setError(false);
    // The ONE copy (lib/clipboard): Clipboard API, else the legacy copy
    // command (a plain-HTTP page has no `navigator.clipboard`).
    void copyText(value).then(done);
  };

  return { isCopied, error, copyToClipboard };
}
