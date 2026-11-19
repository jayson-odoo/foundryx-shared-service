'use client';

import { useCallback, useEffect, useState } from 'react';
import { LoaderCircleIcon } from 'lucide-react';
import { parsePhoneNumberFromString } from 'libphonenumber-js';
import { useSharePhoneStep, type ShareAction } from '@/hooks/use-idea-portal';
import { Button } from '@/components/ui/button';
import { Dialog, DialogBody, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { PhoneInput } from '@/components/platform/phone-input/phone-input';
import { OtpCodeField, useResendCooldown } from '@/components/platform/otp-code-field/otp-code-field';

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
  like: 'Like this comment',
};

/** Seconds before a new code may be asked for (CRM portal `RESEND_COOLDOWN_S`). */
const RESEND_COOLDOWN_S = 60;

function readable(e164: string): string {
  return parsePhoneNumberFromString(e164)?.formatInternational() ?? e164;
}

/** Lane FEEDBACK-SUBSCRIBE: the phone step on a share link. Since lane
 * FEEDBACK-SHARE-SS-HOST (owner 19 Nov) it mirrors the CRM `/signin` phone
 * mode 1:1: the Dealer Access phone field, then the portal code field that
 * checks the code on its own at the 6th digit. */
export function SharePhoneDialog({ shareToken, ideaId, action, onClose, onProven }: SharePhoneDialogProps) {
  const step = useSharePhoneStep(shareToken);
  const cooldown = useResendCooldown();
  const [phone, setPhone] = useState('');
  const [phoneValid, setPhoneValid] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [code, setCode] = useState('');
  const [verifying, setVerifying] = useState(false);
  const open = action !== null;
  const { restart, clearError } = step;

  useEffect(() => {
    if (!open) {
      restart();
      setPhone('');
      setPhoneValid(false);
      setSubmitted(false);
      setCode('');
    }
  }, [open, restart]);

  const send = useCallback(async () => {
    if (await step.sendCode(phone)) {
      setCode('');
      cooldown.start(RESEND_COOLDOWN_S);
    }
  }, [step, phone, cooldown]);

  const submitPhone = async () => {
    setSubmitted(true);
    if (!phoneValid || step.busy) return;
    await send();
  };

  const onComplete = useCallback(
    async (value: string) => {
      setVerifying(true);
      const s = await step.verify(value, action, ideaId);
      setVerifying(false);
      if (s) onProven(s.boardUrl);
      else setCode('');
    },
    [step, action, ideaId, onProven],
  );

  return (
    <Dialog open={open} onOpenChange={(o) => !o && !step.busy && onClose()}>
      <DialogContent className="max-w-md" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>{action ? TITLES[action] : ''}</DialogTitle>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-4">
          {step.step === 'phone' ? (
            <form
              noValidate
              className="flex flex-col gap-4"
              onSubmit={(e) => {
                e.preventDefault();
                void submitPhone();
              }}
            >
              <div className="flex flex-col gap-2">
                <Label htmlFor="share-phone">Phone number</Label>
                <PhoneInput
                  id="share-phone"
                  defaultCountry="MY"
                  autoFocus
                  value={phone}
                  showError={submitted}
                  onChange={(e164, meta) => {
                    setPhone(e164);
                    setPhoneValid(meta.valid);
                    clearError();
                  }}
                />
              </div>
              {step.error && (
                <p className="text-sm text-destructive" role="alert">
                  {step.error}
                </p>
              )}
              <Button type="submit" className="h-11 w-full" disabled={step.busy}>
                {step.busy && <LoaderCircleIcon className="size-4 animate-spin" />}
                Continue
              </Button>
            </form>
          ) : (
            <>
              <div className="flex flex-col items-start gap-1">
                <p className="text-sm text-muted-foreground">
                  We&apos;ll send a code to your WhatsApp {readable(phone)}
                </p>
                <Button
                  type="button"
                  mode="link"
                  size="sm"
                  disabled={step.busy}
                  onClick={() => {
                    setCode('');
                    restart();
                  }}
                >
                  Change number
                </Button>
              </div>
              <OtpCodeField
                id="share-code"
                autoFocus
                value={code}
                onChange={(v) => {
                  setCode(v);
                  clearError();
                }}
                onComplete={(v) => void onComplete(v)}
                cooldown={cooldown.seconds}
                sent
                pending={step.busy}
                onResend={() => void send()}
                status={verifying ? <span>Signing you in as {readable(phone)}</span> : undefined}
              />
              {step.error && (
                <p className="text-sm text-destructive" role="alert">
                  {step.error}
                </p>
              )}
            </>
          )}
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
}
