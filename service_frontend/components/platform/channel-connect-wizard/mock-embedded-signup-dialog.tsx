'use client';

import { useState } from 'react';
import { ArrowLeft, Facebook, Loader2, Phone, Plus } from 'lucide-react';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { cn } from '@/lib/utils';
import { isValidPhone, normalizePhone } from '@/lib/phone';
import type { MockWabaOption } from '@/types/omnichannel';
import { MOCK_WABA_OPTIONS } from '@/services/onboarding-service.mock';

export interface MockEmbeddedSignupDialogProps {
  open: boolean;
  /** True while the backend exchange/provision is in flight. */
  busy: boolean;
  onAuthorize: (option: MockWabaOption) => void;
  onCancel: () => void;
}

/**
 * SIMULATED Meta Embedded Signup popup (Phase A only). Stands in for the real
 * Meta JS SDK so the prototype can demonstrate the "log in → pick (or register)
 * your WhatsApp number → authorize" experience and tune every state. In Phase B
 * this whole component is replaced by the real SDK launch (the wizard's state
 * machine and the backend exchange stay the same).
 *
 * Note: in production the number is registered/selected *inside Meta's popup* —
 * never typed into a FoundryX form. The "register a number" mode here only
 * simulates that Meta step so the prototype is self-contained.
 */
export function MockEmbeddedSignupDialog({
  open,
  busy,
  onAuthorize,
  onCancel,
}: MockEmbeddedSignupDialogProps) {
  const [mode, setMode] = useState<'pick' | 'register'>('pick');
  const [selectedId, setSelectedId] = useState<string>(MOCK_WABA_OPTIONS[0]?.wabaId ?? '');
  const [businessName, setBusinessName] = useState('');
  const [phone, setPhone] = useState('');

  const selected = MOCK_WABA_OPTIONS.find((o) => o.wabaId === selectedId);
  const phoneValid = isValidPhone(phone);
  const showPhoneError = phone.trim().length > 0 && !phoneValid;
  const registerValid = businessName.trim().length > 0 && phoneValid;

  function authorizePicked() {
    if (selected) onAuthorize(selected);
  }

  function authorizeRegistered() {
    if (!registerValid) return;
    const normalized = normalizePhone(phone);
    const id = `new-${normalized.replace(/\D/g, '')}`;
    onAuthorize({
      wabaId: `waba-${id}`,
      businessName: businessName.trim(),
      phoneNumberId: `pn-${id}`,
      displayPhoneNumber: normalized,
    });
  }

  return (
    <Dialog open={open} onOpenChange={(o) => !o && !busy && onCancel()}>
      <DialogContent className="w-full max-w-[460px]" showCloseButton={false}>
        <DialogHeader>
          <div className="flex items-center gap-2.5">
            <span className="flex size-8 items-center justify-center rounded-md bg-[#1877F2] text-white">
              <Facebook className="size-4.5" />
            </span>
            <div>
              <DialogTitle>Connect with Facebook</DialogTitle>
              <DialogDescription className="text-xs">
                Simulated Meta Embedded Signup (prototype)
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        {mode === 'pick' ? (
          <>
            <DialogBody className="flex flex-col gap-3">
              <p className="text-sm text-muted-foreground">
                Select the WhatsApp Business number to connect to this workspace.
              </p>

              <RadioGroup value={selectedId} onValueChange={setSelectedId} className="flex flex-col gap-2">
                {MOCK_WABA_OPTIONS.map((opt) => (
                  <label
                    key={opt.wabaId}
                    htmlFor={`waba-${opt.wabaId}`}
                    className={cn(
                      'flex cursor-pointer items-center gap-3 rounded-lg border p-3 transition-colors',
                      selectedId === opt.wabaId
                        ? 'border-primary bg-primary/5'
                        : 'border-border hover:bg-muted/50',
                    )}
                  >
                    <RadioGroupItem value={opt.wabaId} id={`waba-${opt.wabaId}`} />
                    <span className="flex size-8 items-center justify-center rounded-md bg-[#25D366]/10 text-[#25D366]">
                      <Phone className="size-4" />
                    </span>
                    <span className="flex flex-col">
                      <span className="text-sm font-medium text-foreground">{opt.businessName}</span>
                      <span className="text-xs text-muted-foreground">{opt.displayPhoneNumber}</span>
                    </span>
                  </label>
                ))}
              </RadioGroup>

              <Button
                variant="outline"
                size="sm"
                className="self-start"
                onClick={() => setMode('register')}
                disabled={busy}
              >
                <Plus className="size-4" />
                Register a different number
              </Button>
            </DialogBody>

            <DialogFooter>
              <Button variant="outline" onClick={onCancel} disabled={busy}>
                Cancel
              </Button>
              <Button onClick={authorizePicked} disabled={busy || !selected}>
                {busy && <Loader2 className="size-4 animate-spin" />}
                {busy ? 'Authorizing…' : 'Authorize'}
              </Button>
            </DialogFooter>
          </>
        ) : (
          <>
            <DialogBody className="flex flex-col gap-3">
              <p className="text-sm text-muted-foreground">
                Register a new WhatsApp Business number with Meta. (In production this happens inside
                Meta&apos;s popup; here it&apos;s simulated.)
              </p>
              <div className="flex flex-col gap-1.5">
                <label className="text-sm text-muted-foreground">Business display name</label>
                <Input
                  placeholder="e.g. FoundryX VIP Desk"
                  value={businessName}
                  onChange={(e) => setBusinessName(e.target.value)}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <label className="text-sm text-muted-foreground">Phone number</label>
                <Input
                  placeholder="e.g. +65 8000 0000"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  aria-invalid={showPhoneError}
                />
                {showPhoneError && (
                  <span className="text-xs text-destructive">
                    Enter a valid phone number in international format (e.g. +65 8000 0000).
                  </span>
                )}
              </div>
            </DialogBody>

            <DialogFooter>
              <Button variant="outline" onClick={() => setMode('pick')} disabled={busy}>
                <ArrowLeft className="size-4" />
                Back
              </Button>
              <Button onClick={authorizeRegistered} disabled={busy || !registerValid}>
                {busy && <Loader2 className="size-4 animate-spin" />}
                {busy ? 'Authorizing…' : 'Authorize'}
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
