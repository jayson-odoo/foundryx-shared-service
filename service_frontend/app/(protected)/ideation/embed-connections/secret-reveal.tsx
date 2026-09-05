'use client';

import { Check, Copy } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useCopyToClipboard } from '@/hooks/use-copy-to-clipboard';

/**
 * One-time signing-secret reveal (create + rotate). The plaintext exists
 * client-side only for this moment - the backend stores it Fernet-encrypted and
 * never returns it. The admin copies it now and pastes the SAME value into the
 * host's (sorento's) embed config.
 */
export function SecretReveal({ secret }: { secret: string }) {
  const { isCopied, copyToClipboard } = useCopyToClipboard();

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <Input
          readOnly
          value={secret}
          className="font-mono text-sm"
          aria-label="Signing secret"
          onFocus={(e) => e.currentTarget.select()}
        />
        <Button
          variant="outline"
          mode="icon"
          onClick={() => copyToClipboard(secret)}
          aria-label="Copy signing secret"
        >
          {isCopied ? <Check className="size-4 text-success" /> : <Copy className="size-4" />}
        </Button>
      </div>
      <p className="text-sm font-medium text-destructive">
        Copy this secret now - it won&apos;t be shown again. Paste the SAME value into the host
        app&apos;s embed config.
      </p>
    </div>
  );
}
