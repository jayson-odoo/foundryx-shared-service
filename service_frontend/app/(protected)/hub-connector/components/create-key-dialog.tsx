'use client';

import { useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';
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
import { OneTimeSecret } from '@/components/platform/one-time-secret';
import { hubConnectorErrorMessage, useCreateHubKey } from '@/hooks/use-hub-connector';

export interface CreateKeyDialogProps {
  hubId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: () => void;
}

/** Name the key, then show the full key ONCE. Closing clears it. */
export function CreateKeyDialog({ hubId, open, onOpenChange, onCreated }: CreateKeyDialogProps) {
  const { creating, create } = useCreateHubKey(hubId);
  const [name, setName] = useState('');
  const [fullKey, setFullKey] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setName('');
      setFullKey(null);
    }
  }, [open]);

  const submit = async () => {
    const trimmed = name.trim();
    if (!trimmed || creating) return;
    try {
      const created = await create(trimmed);
      setFullKey(created.key);
      onCreated();
    } catch (err) {
      toast.error(hubConnectorErrorMessage(err, 'Could not create the key. Please try again.'));
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>{fullKey ? 'Key created' : 'Create key'}</DialogTitle>
        </DialogHeader>
        {fullKey ? (
          <>
            <DialogBody>
              <OneTimeSecret value={fullKey} label="Key" />
            </DialogBody>
            <DialogFooter>
              <Button variant="primary" onClick={() => onOpenChange(false)}>
                Done
              </Button>
            </DialogFooter>
          </>
        ) : (
          <>
            <DialogBody className="flex flex-col gap-2">
              <Label htmlFor="hub-key-name">Hub key name *</Label>
              <Input
                id="hub-key-name"
                autoFocus
                maxLength={200}
                placeholder="Hub key"
                value={name}
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    void submit();
                  }
                }}
              />
            </DialogBody>
            <DialogFooter>
              <Button variant="outline" onClick={() => onOpenChange(false)} disabled={creating}>
                Cancel
              </Button>
              <Button variant="primary" onClick={submit} disabled={creating || !name.trim()}>
                {creating && <Loader2 className="size-4 animate-spin" />}
                Create
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
