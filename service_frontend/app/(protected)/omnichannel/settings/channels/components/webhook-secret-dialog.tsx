'use client';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { WebhookSecretPanel } from './webhook-secret-panel';

export interface WebhookSecretDialogProps {
  /** The freshly-rotated secret, or null while closed. */
  secret: string | null;
  onOpenChange: (open: boolean) => void;
}

/**
 * Rotate-result dialog — reveals the freshly-rotated signing secret ONCE.
 * Driven by a nullable `secret` (open ⇔ non-null); closing clears it upstream.
 */
export function WebhookSecretDialog({ secret, onOpenChange }: WebhookSecretDialogProps) {
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
