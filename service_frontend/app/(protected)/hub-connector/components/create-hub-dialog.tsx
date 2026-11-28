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
import { hubConnectorErrorMessage, useCreateHub } from '@/hooks/use-hub-connector';

export interface CreateHubDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: () => void;
}

/** Name, code and receiver URL, then the signing secret ONCE. Closing clears it. */
export function CreateHubDialog({ open, onOpenChange, onCreated }: CreateHubDialogProps) {
  const { creating, create } = useCreateHub();
  const [name, setName] = useState('');
  const [code, setCode] = useState('');
  const [url, setUrl] = useState('');
  const [secret, setSecret] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setName('');
      setCode('');
      setUrl('');
      setSecret(null);
    }
  }, [open]);

  const ready = name.trim() !== '' && code.trim() !== '' && url.trim() !== '';

  const submit = async () => {
    if (!ready || creating) return;
    try {
      const res = await create({ name: name.trim(), code: code.trim(), callbackUrl: url.trim() });
      setSecret(res.signingSecret);
      onCreated();
    } catch (err) {
      toast.error(hubConnectorErrorMessage(err, 'Could not create the hub. Please try again.'));
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>{secret ? 'Hub created' : 'Create hub'}</DialogTitle>
        </DialogHeader>
        {secret ? (
          <>
            <DialogBody>
              <OneTimeSecret value={secret} label="Signing secret" />
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
              <div className="flex flex-col gap-2">
                <Label htmlFor="hub-name">Name *</Label>
                <Input id="hub-name" autoFocus maxLength={200} value={name} onChange={(e) => setName(e.target.value)} />
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor="hub-code">Code *</Label>
                <Input id="hub-code" maxLength={64} value={code} onChange={(e) => setCode(e.target.value)} />
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor="hub-url">Receiver URL *</Label>
                <Input
                  id="hub-url"
                  type="url"
                  inputMode="url"
                  maxLength={500}
                  placeholder="https://"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                />
              </div>
            </DialogBody>
            <DialogFooter>
              <Button variant="outline" onClick={() => onOpenChange(false)} disabled={creating}>
                Cancel
              </Button>
              <Button variant="primary" onClick={submit} disabled={creating || !ready}>
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
