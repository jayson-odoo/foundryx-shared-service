'use client';

import { useState } from 'react';
import { Check, Copy } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

/**
 * One-time signing-secret reveal (create + rotate). The plaintext exists
 * client-side only for this moment - the backend stores it Fernet-encrypted and
 * never returns it. The admin copies it now and pastes the SAME value into the
 * host's (sorento's) embed config.
 */
export function SecretReveal({ secret }: { secret: string }) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(secret);
      setCopied(true);
      toast.success('Signing secret copied to clipboard.');
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error('Could not copy. Select and copy the secret manually.');
    }
  };

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
        <Button variant="outline" mode="icon" onClick={copy} aria-label="Copy signing secret">
          {copied ? <Check className="size-4 text-success" /> : <Copy className="size-4" />}
        </Button>
      </div>
      <p className="text-sm font-medium text-destructive">
        Copy this secret now - it won&apos;t be shown again. Paste the SAME value into the host
        app&apos;s embed config.
      </p>
    </div>
  );
}
