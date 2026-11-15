'use client';

import { useEffect, useState } from 'react';
import { KeyRound, Loader2, RefreshCw } from 'lucide-react';
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
import { SearchSelect } from '@/components/platform/search-select';
import { embedConnectionService } from '@/services/embed-connection-service';
import type { Product } from '@/types/ideation';
import { OriginsInput } from './origins-input';
import { SecretReveal } from './secret-reveal';
import { generateSigningSecret } from './generate-secret';

export interface EmbedConnectionCreateDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  products: Product[];
  /** Called after a successful create so the list can refresh. */
  onCreated: () => void;
}

const MIN_SECRET = 8;

/**
 * Register an embed connection, then reveal the signing secret ONCE. The admin
 * either types a secret or clicks Generate for a strong random one; on create the
 * SAME value is revealed (copyable) so it can be pasted into the host's embed
 * config. The plaintext lives client-side only - the backend stores it encrypted
 * and never returns it. Closing clears every field (never leave a plaintext).
 */
export function EmbedConnectionCreateDialog({
  open,
  onOpenChange,
  products,
  onCreated,
}: EmbedConnectionCreateDialogProps) {
  const [connectionId, setConnectionId] = useState('');
  const [origins, setOrigins] = useState<string[]>([]);
  const [productId, setProductId] = useState<string | null>(null);
  const [secret, setSecret] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Once set, the create succeeded → reveal the secret once (this value only).
  const [revealed, setRevealed] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setConnectionId('');
      setOrigins([]);
      setProductId(null);
      setSecret('');
      setSaving(false);
      setError(null);
      setRevealed(null);
    }
  }, [open]);

  const valid = connectionId.trim().length > 0 && secret.trim().length >= MIN_SECRET;

  const submit = async () => {
    if (!valid) return;
    setSaving(true);
    setError(null);
    try {
      await embedConnectionService.create({
        connectionId: connectionId.trim(),
        signingSecret: secret,
        allowedOrigins: origins,
        productId: productId ?? null,
      });
      setRevealed(secret);
      onCreated();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not create the connection.');
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{revealed ? 'Embed connection created' : 'Add embed connection'}</DialogTitle>
          {!revealed && (
            <DialogDescription>
              Register a host app allowed to embed this tenant&apos;s Ideas workspace. Both sides must
              hold the same connection id + signing secret.
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
                <Label htmlFor="conn-id">
                  Connection id <span className="text-destructive">*</span>
                </Label>
                <Input
                  id="conn-id"
                  autoFocus
                  placeholder="e.g. sorento-ideation"
                  value={connectionId}
                  onChange={(e) => setConnectionId(e.target.value)}
                />
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="conn-origins">Allowed origins</Label>
                <OriginsInput id="conn-origins" value={origins} onChange={setOrigins} />
              </div>

              <div className="space-y-1.5">
                <Label>Product scope</Label>
                <SearchSelect
                  options={products.map((p) => ({ label: p.name, value: p.id }))}
                  value={productId}
                  onChange={setProductId}
                  placeholder="All ideas (no product scope)"
                />
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="conn-secret">
                  Signing secret <span className="text-destructive">*</span>
                </Label>
                <div className="flex items-center gap-2">
                  <Input
                    id="conn-secret"
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
                <p className="text-xs text-muted-foreground">
                  Shown once after create - copy it then. Stored encrypted; never shown again.
                </p>
              </div>

              {error && <p className="text-sm text-destructive">{error}</p>}
            </DialogBody>
            <DialogFooter>
              <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
                Cancel
              </Button>
              <Button variant="primary" onClick={submit} disabled={!valid || saving}>
                {saving ? <Loader2 className="size-4 animate-spin" /> : <KeyRound className="size-4" />}
                {saving ? 'Creating…' : 'Create connection'}
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
