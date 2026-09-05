'use client';

import { useState } from 'react';
import { Check, Copy } from 'lucide-react';
import { toast } from '@/lib/toast';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

export interface WebhookSecretPanelProps {
  secret: string;
}

/**
 * One-time signing-secret reveal - a readonly input + copy button + a "won't be
 * shown again" line. Shared by the create dialog (post-submit) and the rotate
 * dialog. The signature-verification convention is a single-line field
 * description, not a tutorial.
 */
export function WebhookSecretPanel({ secret }: WebhookSecretPanelProps) {
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
        Copy this secret now - it won&apos;t be shown again.
      </p>
      <p className="text-xs text-muted-foreground">
        Sent as{' '}
        <code className="rounded bg-muted px-1 py-0.5 font-mono">
          X-Fx-Signature: sha256=HMAC(secret, timestamp.body)
        </code>
      </p>
    </div>
  );
}
