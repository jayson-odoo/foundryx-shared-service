'use client';

import { OneTimeSecret } from '@/components/platform/one-time-secret';
import { useFx } from '@/hooks/use-fx';
import { FxSecretOnce } from '@/components/fx/fields';

export interface WebhookSecretPanelProps {
  secret: string;
}

/**
 * One-time signing-secret reveal (shared `OneTimeSecret`) + the signature
 * header convention line. Shared by the create dialog (post-submit) and the
 * rotate dialog.
 */
export function WebhookSecretPanel(props: WebhookSecretPanelProps) {
  return useFx() ? <FxWebhookSecretPanel {...props} /> : <WebhookSecretPanelLegacy {...props} />;
}

/** Foundryx UIUX switch only (gap audit 11 "Shown once"): read-only,
 *  monospace, a Copy icon button beside it, one warning line under it. */
function FxWebhookSecretPanel({ secret }: WebhookSecretPanelProps) {
  return (
    <div className="flex flex-col gap-3">
      <FxSecretOnce value={secret} label="Signing secret" />
      <p className="text-sm text-(--fx-ink-3)">
        Sent as{' '}
        <code className="rounded-(--fx-r-s) bg-(--fx-surface-2) px-1 py-0.5 font-mono text-(--fx-ink-2)">
          X-Fx-Signature: sha256=HMAC(secret, timestamp.body)
        </code>
      </p>
    </div>
  );
}

function WebhookSecretPanelLegacy({ secret }: WebhookSecretPanelProps) {
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
