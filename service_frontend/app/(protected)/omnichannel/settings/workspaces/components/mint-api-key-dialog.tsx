'use client';

import { useEffect, useState } from 'react';
import { Check, Copy, KeyRound, Loader2 } from 'lucide-react';
import { toast } from '@/lib/toast';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useApiKeys } from './use-api-keys';

export interface MintApiKeyDialogProps {
  workspaceId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Called after a successful mint so the list can refresh. */
  onMinted: () => void;
}

/**
 * Mint dialog - name the key, then reveal the full plaintext ONCE. The reveal
 * step is the only time the plaintext exists client-side; closing clears it.
 */
export function MintApiKeyDialog({
  workspaceId,
  open,
  onOpenChange,
  onMinted,
}: MintApiKeyDialogProps) {
  const { mint, minting } = useApiKeys(workspaceId);
  const [name, setName] = useState('');
  const [fullKey, setFullKey] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  // Clear all state whenever the dialog closes (never leave a plaintext key).
  useEffect(() => {
    if (!open) {
      setName('');
      setFullKey(null);
      setCopied(false);
    }
  }, [open]);

  const submit = async () => {
    const trimmed = name.trim();
    if (!trimmed) return;
    try {
      const result = await mint(trimmed);
      setFullKey(result.fullKey);
      onMinted();
    } catch {
      toast.error('Could not mint the key. Please retry.');
    }
  };

  const copy = async () => {
    if (!fullKey) return;
    try {
      await navigator.clipboard.writeText(fullKey);
      setCopied(true);
      toast.success('API key copied to clipboard.');
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error('Could not copy. Select and copy the key manually.');
    }
  };

  const revealed = fullKey !== null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{revealed ? 'API key created' : 'Mint API key'}</DialogTitle>
        </DialogHeader>

        {!revealed ? (
          <>
            <DialogBody className="flex flex-col gap-2">
              <Label htmlFor="api-key-name">Key name</Label>
              <Input
                id="api-key-name"
                autoFocus
                placeholder="e.g. Production server"
                value={name}
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && name.trim() && !minting) {
                    e.preventDefault();
                    void submit();
                  }
                }}
              />
            </DialogBody>
            <DialogFooter>
              <Button variant="outline" onClick={() => onOpenChange(false)} disabled={minting}>
                Cancel
              </Button>
              <Button variant="primary" onClick={submit} disabled={minting || !name.trim()}>
                {minting ? <Loader2 className="size-4 animate-spin" /> : <KeyRound className="size-4" />}
                {minting ? 'Minting…' : 'Mint key'}
              </Button>
            </DialogFooter>
          </>
        ) : (
          <>
            <DialogBody className="flex flex-col gap-3">
              <div className="flex items-center gap-2">
                <Input
                  readOnly
                  value={fullKey ?? ''}
                  className="font-mono text-sm"
                  aria-label="API key"
                  onFocus={(e) => e.currentTarget.select()}
                />
                <Button
                  variant="outline"
                  mode="icon"
                  onClick={copy}
                  aria-label="Copy API key"
                >
                  {copied ? <Check className="size-4 text-success" /> : <Copy className="size-4" />}
                </Button>
              </div>
              <p className="text-sm font-medium text-destructive">
                Copy this key now - it won&apos;t be shown again.
              </p>
            </DialogBody>
            <DialogFooter>
              <Button variant="primary" onClick={() => onOpenChange(false)}>
                Done
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
