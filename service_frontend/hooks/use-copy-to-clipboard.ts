'use client';

import * as React from 'react';

/** The pre-Clipboard-API copy: select a hidden textarea and run the browser's
 * own copy command. True when the browser says it copied. */
function legacyCopy(value: string): boolean {
  try {
    const area = document.createElement('textarea');
    area.value = value;
    area.setAttribute('readonly', '');
    area.className = 'fixed -left-[9999px] top-0 opacity-0';
    // Inside a modal, attach within it: a focus trap would otherwise pull
    // focus back out of a textarea placed on <body>.
    const host = document.activeElement?.closest('[role="dialog"]') ?? document.body;
    host.appendChild(area);
    area.focus();
    area.select();
    const ok = typeof document.execCommand === 'function' && document.execCommand('copy');
    host.removeChild(area);
    return Boolean(ok);
  } catch {
    return false;
  }
}

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
    // Crew pass 70e96f2b: a plain-HTTP page (not a secure context) has NO
    // `navigator.clipboard` at all - the old guard threw a TypeError and the
    // user saw nothing. Fall back to the legacy hidden-textarea copy there.
    const clipboard = typeof navigator !== 'undefined' ? navigator.clipboard : undefined;
    if (!clipboard?.writeText) {
      done(legacyCopy(value));
      return;
    }
    clipboard.writeText(value).then(
      () => done(true),
      () => done(legacyCopy(value)),
    );
  };

  return { isCopied, error, copyToClipboard };
}
