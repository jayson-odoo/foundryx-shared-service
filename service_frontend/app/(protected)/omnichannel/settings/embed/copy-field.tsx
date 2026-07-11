'use client';

import { Check, Copy } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useCopyToClipboard } from '@/hooks/use-copy-to-clipboard';

export interface CopyFieldProps {
  value: string;
  ariaLabel: string;
  /** Render as a multi-line code block instead of a single-line input. */
  multiline?: boolean;
  /** Mask the value as a password field (still copyable). */
  secret?: boolean;
}

/**
 * A read-only value with a Copy button — the reusable "copy this token/snippet"
 * primitive for the embed screen (connection id, secret, iframe snippet).
 */
export function CopyField({ value, ariaLabel, multiline, secret }: CopyFieldProps) {
  const { isCopied, copyToClipboard } = useCopyToClipboard();

  return (
    <div className="flex items-start gap-2">
      {multiline ? (
        <pre className="min-w-0 flex-1 overflow-x-auto rounded-md border border-input bg-muted px-3 py-2 text-xs leading-relaxed text-foreground">
          <code>{value}</code>
        </pre>
      ) : (
        <Input
          readOnly
          type={secret ? 'password' : 'text'}
          value={value}
          aria-label={ariaLabel}
          className="min-w-0 flex-1 font-mono text-xs"
          onFocus={(e) => e.currentTarget.select()}
        />
      )}
      <Button
        type="button"
        variant="outline"
        mode="icon"
        aria-label={`Copy ${ariaLabel}`}
        onClick={() => copyToClipboard(value)}
      >
        {isCopied ? <Check className="text-green-600" /> : <Copy />}
      </Button>
    </div>
  );
}
