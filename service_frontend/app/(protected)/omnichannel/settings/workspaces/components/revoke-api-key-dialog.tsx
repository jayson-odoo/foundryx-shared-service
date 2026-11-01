'use client';

import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';

export interface RevokeApiKeyDialogProps {
  /** The key being revoked; null while closed. */
  keyName: string | null;
  endpointCount: number;
  onConfirm: (pauseEndpoints: boolean) => void;
  onCancel: () => void;
}

/**
 * Revoke choice for a key that registered webhook endpoints: pause them too
 * (on by default) or leave them running, e.g. during a key rotation.
 */
export function RevokeApiKeyDialog({
  keyName,
  endpointCount,
  onConfirm,
  onCancel,
}: RevokeApiKeyDialogProps) {
  const [pause, setPause] = useState(true);
  const open = keyName !== null;

  useEffect(() => {
    if (open) setPause(true);
  }, [open]);

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onCancel()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Revoke {keyName}</DialogTitle>
          <DialogDescription>
            {endpointCount} webhook {endpointCount === 1 ? 'endpoint' : 'endpoints'} registered by this key
          </DialogDescription>
        </DialogHeader>
        <DialogBody>
          <div className="flex items-center gap-2">
            <Checkbox
              id="revoke-pause-endpoints"
              checked={pause}
              onCheckedChange={(v) => setPause(v === true)}
            />
            <Label htmlFor="revoke-pause-endpoints">Also pause them</Label>
          </div>
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={onCancel}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={() => onConfirm(pause)}>
            Revoke
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
