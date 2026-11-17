'use client';

import { useEffect, useState } from 'react';
import { Loader2, RefreshCw } from 'lucide-react';
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
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { embedConnectionService } from '@/services/embed-connection-service';
import { SecretReveal } from './secret-reveal';
import { generateSigningSecret } from './generate-secret';

export interface RotateSecretDialogProps {
  /** The connection to rotate, or null when the dialog is closed. */
  connectionId: string | null;
  onOpenChange: (open: boolean) => void;
  /** Called after a successful rotate so the list can refresh. */
  onRotated: () => void;
}

const MIN_SECRET = 8;

/**
 * Rotate a connection's signing secret, then reveal the new value ONCE. Rotating
 * invalidates every assertion signed with the old secret - the host must be
 * updated with the new value at the same time. The plaintext lives client-side
 * only; the backend stores it encrypted and never returns it.
 */
export function RotateSecretDialog({ connectionId, onOpenChange, onRotated }: RotateSecretDialogProps) {
  const open = connectionId !== null;
  const [secret, setSecret] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [revealed, setRevealed] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setSecret('');
      setSaving(false);
      setError(null);
      setRevealed(null);
    }
  }, [open]);

  const valid = secret.trim().length >= MIN_SECRET;

  const submit = async () => {
    if (!valid || !connectionId) return;
    setSaving(true);
    setError(null);
    try {
      await embedConnectionService.rotate(connectionId, secret);
      setRevealed(secret);
      onRotated();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not rotate the secret.');
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{revealed ? 'Secret rotated' : 'Rotate signing secret'}</DialogTitle>
          {!revealed && (
            <DialogDescription>
              Set a new signing secret for <span className="font-mono">{connectionId}</span>. Every
              assertion signed with the old secret stops working immediately - update the host at the
              same time.
            </DialogDescription>
          )}
        </DialogHeader>

        {revealed ? (
          <>
            <DialogBody>
              <SecretReveal secret={revealed} />
            </DialogBody>
            <DialogFooter>
              <Button variant="primary" onClick={() => onOpenChange(false)}>
                Done
              </Button>
            </DialogFooter>
          </>
        ) : (
          <>
            <DialogBody className="space-y-4">
              <div className="space-y-1.5">
                <Label htmlFor="rotate-secret">
                  New signing secret <span className="text-destructive">*</span>
                </Label>
                <div className="flex items-center gap-2">
                  <Input
                    id="rotate-secret"
                    autoFocus
                    className="font-mono text-sm"
                    placeholder="At least 8 characters, or generate one"
                    value={secret}
                    onChange={(e) => setSecret(e.target.value)}
                  />
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => setSecret(generateSigningSecret())}
                  >
                    <RefreshCw className="size-4" />
                    Generate
                  </Button>
                </div>
              </div>
              {error && <p className="text-sm text-destructive">{error}</p>}
            </DialogBody>
            <DialogFooter>
              <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
                Cancel
              </Button>
              <Button variant="primary" onClick={submit} disabled={!valid || saving}>
                {saving ? <Loader2 className="size-4 animate-spin" /> : <RefreshCw className="size-4" />}
                {saving ? 'Rotating…' : 'Rotate secret'}
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
