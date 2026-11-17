'use client';

import { useEffect, useState } from 'react';
import { LoaderCircleIcon } from 'lucide-react';
import { useSharePhoneStep, type ShareAction } from '@/hooks/use-idea-portal';
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

export interface SharePhoneDialogProps {
  shareToken: string;
  ideaId: string;
  /** The tap that opened it (null = closed). */
  action: ShareAction | null;
  onClose: () => void;
  /** Proven: where the visitor continues (their own board link), or null. */
  onProven: (boardUrl: string | null) => void;
}

const TITLES: Record<ShareAction, string> = {
  follow: 'Follow this request',
  upvote: 'Upvote this request',
  comment: 'Comment on this request',
};

/** Lane FEEDBACK-SUBSCRIBE: the phone step on a share link. Step 1 phone ->
 * the item's product sends a WhatsApp code; step 2 code -> the visitor
 * continues as themselves. */
export function SharePhoneDialog({ shareToken, ideaId, action, onClose, onProven }: SharePhoneDialogProps) {
  const step = useSharePhoneStep(shareToken);
  const [phone, setPhone] = useState('');
  const [code, setCode] = useState('');
  const open = action !== null;
  const { restart } = step;

  useEffect(() => {
    if (!open) {
      restart();
      setCode('');
    }
  }, [open, restart]);

  const submitPhone = async () => {
    if (!phone.trim() || step.busy) return;
    if (await step.sendCode(phone.trim())) setCode('');
  };
  const submitCode = async () => {
    if (!code.trim() || step.busy) return;
    const s = await step.verify(code.trim(), action, ideaId);
    if (s) onProven(s.boardUrl);
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && !step.busy && onClose()}>
      <DialogContent className="max-w-sm" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>{action ? TITLES[action] : ''}</DialogTitle>
        </DialogHeader>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void (step.step === 'phone' ? submitPhone() : submitCode());
          }}
        >
          <DialogBody className="flex flex-col gap-2">
            {step.step === 'phone' ? (
              <>
                <Label htmlFor="share-phone">Your WhatsApp number</Label>
                <Input
                  id="share-phone"
                  type="tel"
                  inputMode="tel"
                  autoComplete="tel"
                  autoFocus
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                />
              </>
            ) : (
              <>
                <Label htmlFor="share-code">Code sent to {phone}</Label>
                <Input
                  id="share-code"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  maxLength={8}
                  autoFocus
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
                />
                <Button type="button" mode="link" size="sm" className="self-start" onClick={restart}>
                  Send a new code
                </Button>
              </>
            )}
            {step.error && (
              <p className="text-sm text-destructive" role="alert">
                {step.error}
              </p>
            )}
          </DialogBody>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose} disabled={step.busy}>
              Cancel
            </Button>
            <Button type="submit" disabled={step.busy || !(step.step === 'phone' ? phone.trim() : code.trim())}>
              {step.busy && <LoaderCircleIcon className="size-3.5 animate-spin" />}
              {step.step === 'phone' ? 'Send code' : 'Continue'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
