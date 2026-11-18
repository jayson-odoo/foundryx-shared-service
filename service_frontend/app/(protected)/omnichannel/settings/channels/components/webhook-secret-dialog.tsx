'use client';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { useFx } from '@/hooks/use-fx';
import {
  FX_DIALOG_CLASS,
  FX_DIALOG_TITLE_CLASS,
  FxDialogFooter,
  FxHideMainWhile,
} from '@/components/platform/channel-connect-wizard/fx-dialog-parts';
import { WebhookSecretPanel } from './webhook-secret-panel';

export interface WebhookSecretDialogProps {
  /** The freshly-rotated secret, or null while closed. */
  secret: string | null;
  /** Foundryx UIUX switch only: the endpoint's name, for the title. */
  name?: string;
  onOpenChange: (open: boolean) => void;
}

/**
 * Rotate-result dialog - reveals the freshly-rotated signing secret ONCE.
 * Driven by a nullable `secret` (open ⇔ non-null); closing clears it upstream.
 */
export function WebhookSecretDialog(props: WebhookSecretDialogProps) {
  return useFx() ? <FxWebhookSecretDialog {...props} /> : <WebhookSecretDialogLegacy {...props} />;
}

/** Foundryx UIUX switch only: the new secret shown once, one "Done". */
function FxWebhookSecretDialog({ secret, name, onOpenChange }: WebhookSecretDialogProps) {
  return (
    <Dialog open={secret !== null} onOpenChange={onOpenChange}>
      <FxHideMainWhile open={secret !== null} />
      <DialogContent className={FX_DIALOG_CLASS}>
        <DialogTitle className={FX_DIALOG_TITLE_CLASS}>
          {name ? `New signing secret for ${name}` : 'New signing secret'}
        </DialogTitle>
        <DialogDescription className="sr-only">New signing secret</DialogDescription>
        {secret && <WebhookSecretPanel secret={secret} />}
        <FxDialogFooter action={{ label: 'Done', onClick: () => onOpenChange(false) }} />
      </DialogContent>
    </Dialog>
  );
}

function WebhookSecretDialogLegacy({ secret, onOpenChange }: WebhookSecretDialogProps) {
  return (
    <Dialog open={secret !== null} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Signing secret rotated</DialogTitle>
        </DialogHeader>
        <DialogBody>{secret && <WebhookSecretPanel secret={secret} />}</DialogBody>
        <DialogFooter>
          <Button variant="primary" onClick={() => onOpenChange(false)}>
            Done
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
