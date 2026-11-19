'use client';

import { Check, Copy } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useCopyToClipboard } from '@/hooks/use-copy-to-clipboard';
import { useFx } from '@/hooks/use-fx';
import { FxSecretOnce } from '@/components/fx/fields';

export interface WebhookSecretPanelProps {
  secret: string;
}

/**
 * One-time signing-secret reveal - a readonly input + copy button + a "won't be
 * shown again" line. Shared by the create dialog (post-submit) and the rotate
 * dialog. The signature-verification convention is a single-line field
 * description, not a tutorial.
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
  const { isCopied, error, copyToClipboard } = useCopyToClipboard();

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
      {error && (
        <p className="text-sm font-medium text-destructive">
          Could not copy. Select and copy manually.
        </p>
      )}
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
