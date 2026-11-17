'use client';

import { OneTimeSecret } from '@/components/platform/one-time-secret';

export interface WebhookSecretPanelProps {
  secret: string;
}

/**
 * One-time signing-secret reveal (shared `OneTimeSecret`) + the signature
 * header convention line. Shared by the create dialog (post-submit) and the
 * rotate dialog.
 */
export function WebhookSecretPanel({ secret }: WebhookSecretPanelProps) {
  return (
    <div className="flex flex-col gap-3">
      <OneTimeSecret value={secret} label="Signing secret" />
      <p className="text-xs text-muted-foreground">
        Sent as{' '}
        <code className="rounded bg-muted px-1 py-0.5 font-mono">
          X-Fx-Signature: sha256=HMAC(secret, timestamp.body)
        </code>
      </p>
    </div>
  );
}
