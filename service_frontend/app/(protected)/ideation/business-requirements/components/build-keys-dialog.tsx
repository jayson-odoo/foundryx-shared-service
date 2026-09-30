'use client';

import { useCallback, useEffect, useState } from 'react';
import { Check, Copy, KeyRound, Trash2 } from 'lucide-react';
import { toast } from '@/lib/toast';
import { Button } from '@/components/ui/button';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
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
import { ClampedText } from '@/components/platform/clamped-text';
import { useCopyToClipboard } from '@/hooks/use-copy-to-clipboard';
import { useDatetime } from '@/hooks/use-datetime';
import { businessRequirementService } from '@/services/business-requirement-service';
import type { BuildKey } from '@/types/business-requirement';

export interface BuildKeysDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * Build write-back keys (AC-STB-15): list, mint (name) and revoke. The plaintext
 * is shown exactly ONCE with a copy control; closing clears every field,
 * including the plaintext - it is never persisted or re-derivable afterwards.
 */
export function BuildKeysDialog({ open, onOpenChange }: BuildKeysDialogProps) {
  const { formatDateTime } = useDatetime();
  const { isCopied, copyToClipboard } = useCopyToClipboard();
  const [keys, setKeys] = useState<BuildKey[]>([]);
  const [loading, setLoading] = useState(false);
  const [name, setName] = useState('');
  const [minting, setMinting] = useState(false);
  const [plaintext, setPlaintext] = useState<string | null>(null);
  const [revoking, setRevoking] = useState<BuildKey | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      setKeys(await businessRequirementService.listBuildKeys());
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not load the keys.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) {
      void reload();
      return;
    }
    setName('');
    setPlaintext(null);
    setRevoking(null);
  }, [open, reload]);

  async function mint() {
    if (minting || !name.trim()) return;
    setMinting(true);
    try {
      const minted = await businessRequirementService.mintBuildKey(name.trim());
      setPlaintext(minted.plaintext);
      setName('');
      void reload();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not mint the key.');
    } finally {
      setMinting(false);
    }
  }

  async function revoke(key: BuildKey) {
    try {
      await businessRequirementService.revokeBuildKey(key.id);
      toast.success('Key revoked.');
      void reload();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not revoke the key.');
    }
  }

  const revealed = plaintext !== null;

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{revealed ? 'Key minted' : 'Build write-back keys'}</DialogTitle>
          </DialogHeader>

          {revealed ? (
            <>
              <DialogBody className="flex flex-col gap-3">
                <div className="flex items-center gap-2">
                  <Input
                    readOnly
                    value={plaintext ?? ''}
                    className="font-mono text-sm"
                    aria-label="Plaintext key"
                    onFocus={(e) => e.currentTarget.select()}
                  />
                  <Button
                    variant="outline"
                    mode="icon"
                    onClick={() => copyToClipboard(plaintext ?? '')}
                    aria-label="Copy key"
                  >
                    {isCopied ? <Check className="size-4 text-success" /> : <Copy className="size-4" />}
                  </Button>
                </div>
                <p className="text-sm font-medium text-destructive">
                  Copy this key now - it will not be shown again.
                </p>
              </DialogBody>
              <DialogFooter>
                <Button variant="primary" onClick={() => onOpenChange(false)}>
                  Done
                </Button>
              </DialogFooter>
            </>
          ) : (
            <>
              <DialogBody className="flex flex-col gap-4">
                <div className="flex items-end gap-2">
                  <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                    <Label htmlFor="build-key-name">Name</Label>
                    <Input
                      id="build-key-name"
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') void mint();
                      }}
                    />
                  </div>
                  <Button
                    variant="primary"
                    onClick={() => void mint()}
                    disabled={minting || !name.trim()}
                  >
                    <KeyRound />
                    Mint
                  </Button>
                </div>

                {keys.length > 0 && (
                  <ul className="flex flex-col divide-y rounded-md border">
                    {keys.map((key) => (
                      <li key={key.id} className="flex items-center gap-3 px-3 py-2">
                        <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                          <ClampedText text={key.name} lines={1} className="text-sm font-medium" />
                          <span className="font-mono text-xs text-muted-foreground">
                            {key.keyPrefix}
                          </span>
                          <span className="text-xs text-muted-foreground">
                            {`Created ${formatDateTime(key.createdAt)}`}
                            {key.lastUsedAt ? ` · Last used ${formatDateTime(key.lastUsedAt)}` : ''}
                          </span>
                        </div>
                        <Button
                          variant="ghost"
                          size="sm"
                          mode="icon"
                          aria-label={`Revoke ${key.name}`}
                          onClick={() => setRevoking(key)}
                        >
                          <Trash2 />
                        </Button>
                      </li>
                    ))}
                  </ul>
                )}
                {!loading && keys.length === 0 && (
                  <p className="text-sm text-muted-foreground">No keys yet.</p>
                )}
              </DialogBody>
              <DialogFooter>
                <Button variant="outline" onClick={() => onOpenChange(false)}>
                  Close
                </Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>

      <AlertDialog open={revoking !== null} onOpenChange={(next) => !next && setRevoking(null)}>
        <AlertDialogContent className="md:max-w-[400px]">
          <AlertDialogHeader>
            <AlertDialogTitle>Revoke key?</AlertDialogTitle>
            <AlertDialogDescription>
              {revoking ? `${revoking.name} stops working immediately.` : ''}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                const target = revoking;
                setRevoking(null);
                if (target) void revoke(target);
              }}
            >
              Revoke
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
