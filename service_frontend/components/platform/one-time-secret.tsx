'use client';

import { Check, Copy } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useCopyToClipboard } from '@/hooks/use-copy-to-clipboard';

export interface OneTimeSecretProps {
  /** The plaintext, shown this once. */
  value: string;
  /** Accessible name and the noun in the warning, e.g. "Signing secret", "Key". */
  label: string;
}

/**
 * One-time reveal of a key or secret: readonly input + Copy + the "won't be
 * shown again" line. Shared by every "created, copy it now" dialog.
 */
export function OneTimeSecret({ value, label }: OneTimeSecretProps) {
  const { isCopied, error, copyToClipboard } = useCopyToClipboard();

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <Input
          readOnly
          value={value}
          className="font-mono text-sm"
          aria-label={label}
          onFocus={(e) => e.currentTarget.select()}
        />
        <Button
          variant="outline"
          mode="icon"
          onClick={() => copyToClipboard(value)}
          aria-label={`Copy ${label.toLowerCase()}`}
        >
          {isCopied ? <Check className="size-4 text-success" /> : <Copy className="size-4" />}
        </Button>
      </div>
      {error && (
        <p className="text-sm font-medium text-destructive">
          Could not copy. Select and copy manually.
        </p>
      )}
      <p className="text-sm font-medium text-destructive">
        Copy this {label.toLowerCase()} now - it won&apos;t be shown again.
      </p>
    </div>
  );
}
