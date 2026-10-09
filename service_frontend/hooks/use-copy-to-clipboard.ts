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

  const copyToClipboard = (value: string) => {
    if (typeof window === 'undefined' || !navigator.clipboard.writeText) {
      return;
    }

    if (!value) return;

    setError(false);

    navigator.clipboard.writeText(value).then(
      () => {
        setIsCopied(true);

        if (onCopy) {
          onCopy();
        }

        setTimeout(() => {
          setIsCopied(false);
        }, timeout);
      },
      () => {
        // T7 carry-over C2: a rejected writeText (denied permission, no
        // secure context, etc.) used to only console.error - the user saw
        // nothing happen at all. Surface it the same inline, non-toast way
        // a successful copy is surfaced (AC-DLA-53's own ruling: this
        // control's feedback lives beside the control, not in a toast).
        setError(true);

        setTimeout(() => {
          setError(false);
        }, timeout);
      },
    );
  };

  return { isCopied, error, copyToClipboard };
}
