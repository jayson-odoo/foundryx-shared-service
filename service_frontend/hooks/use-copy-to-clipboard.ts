'use client';

import * as React from 'react';

export function useCopyToClipboard({
  timeout = 2000,
  onCopy,
}: {
  timeout?: number;
  onCopy?: () => void;
} = {}) {
  const [isCopied, setIsCopied] = React.useState(false);
  const [error, setError] = React.useState(false);

  const succeeded = () => {
    setIsCopied(true);
    if (onCopy) onCopy();
    setTimeout(() => {
      setIsCopied(false);
    }, timeout);
  };

  const failed = () => {
    // T7 carry-over C2: a failed copy is surfaced beside the control (the
    // caller's inline "Could not copy" line), never silently dropped.
    setError(true);
    setTimeout(() => {
      setError(false);
    }, timeout);
  };

  const copyToClipboard = (value: string) => {
    if (typeof window === 'undefined' || !value) return;
    setError(false);

    // `navigator.clipboard` only exists in a secure context (https or
    // localhost): on a plain-http host it is undefined, so fall back to the
    // legacy copy command and report a failure instead of throwing.
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(value).then(succeeded, failed);
      return;
    }
    if (legacyCopy(value)) succeeded();
    else failed();
  };

  return { isCopied, error, copyToClipboard };
}

/** Copy through a temporary textarea (works without the async clipboard API). */
function legacyCopy(value: string): boolean {
  if (typeof document === 'undefined') return false;
  const area = document.createElement('textarea');
  area.value = value;
  area.setAttribute('readonly', '');
  area.style.position = 'fixed';
  area.style.opacity = '0';
  document.body.appendChild(area);
  area.select();
  let ok = false;
  try {
    ok = typeof document.execCommand === 'function' && document.execCommand('copy');
  } catch {
    ok = false;
  }
  document.body.removeChild(area);
  return ok;
}
