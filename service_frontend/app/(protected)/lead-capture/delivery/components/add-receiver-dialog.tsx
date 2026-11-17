'use client';

import { useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';
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
import { MultiSelect } from '@/components/platform/multi-select';
import { OneTimeSecret } from '@/components/platform/one-time-secret';
import { leadCaptureErrorMessage, useCreateLeadReceiver } from '@/hooks/use-lead-capture';
import { LEAD_EVENT_LABELS, type LeadEvent } from '@/types/lead-capture';

export interface AddReceiverDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onAdded: () => void;
}

const EVENT_OPTIONS = (Object.keys(LEAD_EVENT_LABELS) as LeadEvent[]).map((value) => ({
  value,
  label: LEAD_EVENT_LABELS[value],
}));

/** URL + events, then the signing secret ONCE. Closing clears it. */
export function AddReceiverDialog({ open, onOpenChange, onAdded }: AddReceiverDialogProps) {
  const { creating, create } = useCreateLeadReceiver();
  const [url, setUrl] = useState('');
  const [events, setEvents] = useState<string[]>(['lead.created']);
  const [secret, setSecret] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setUrl('');
      setEvents(['lead.created']);
      setSecret(null);
      setError(null);
    }
  }, [open]);

  const ready = url.trim().length > 0 && events.length > 0 && !creating;

  const submit = async () => {
    if (!ready) return;
    setError(null);
    try {
      const created = await create(url.trim(), events as LeadEvent[]);
      setSecret(created.secret);
      onAdded();
    } catch (err) {
      setError(leadCaptureErrorMessage(err, 'Could not add the receiver. Please try again.'));
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{secret ? 'Receiver added' : 'Add receiver'}</DialogTitle>
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
                <Label htmlFor="lead-receiver-url">URL *</Label>
                <Input
                  id="lead-receiver-url"
                  type="url"
                  inputMode="url"
                  autoFocus
                  maxLength={2048}
                  placeholder="https://"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  aria-invalid={error ? true : undefined}
                />
                {error && <p className="text-sm text-destructive">{error}</p>}
              </div>
              <div className="flex flex-col gap-2">
                <Label>Events *</Label>
                <MultiSelect options={EVENT_OPTIONS} value={events} onChange={setEvents} />
              </div>
            </DialogBody>
            <DialogFooter>
              <Button variant="outline" onClick={() => onOpenChange(false)} disabled={creating}>
                Cancel
              </Button>
              <Button variant="primary" onClick={submit} disabled={!ready}>
                {creating && <Loader2 className="size-4 animate-spin" />}
                Add
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
