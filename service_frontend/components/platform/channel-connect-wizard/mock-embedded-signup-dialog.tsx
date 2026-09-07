'use client';

import { useMemo, useState } from 'react';
import { ArrowLeft, Loader2, Phone, Plus } from 'lucide-react';
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
import { CHANNEL_CAPABILITIES } from '@/lib/channel-capabilities';
import type { ChannelType, MetaPageOption, MockWabaOption } from '@/types/omnichannel';
import { MOCK_WABA_OPTIONS, mockMetaPageOptions } from '@/services/onboarding-service.mock';

export interface MockEmbeddedSignupDialogProps {
  open: boolean;
  channelType: ChannelType;
  /** True while the backend exchange/provision is in flight. */
  busy: boolean;
  onAuthorizeWaba: (option: MockWabaOption) => void;
  onAuthorizeMeta: (option: MetaPageOption) => void;
  onCancel: () => void;
}

/**
 * SIMULATED Meta popup (dev / no Meta app configured). Stands in for the real
 * Meta JS SDK / OAuth dialog so the wizard demonstrates "log in -> pick your
 * number/page -> authorize" end to end without a Meta app. One dialog for all
 * three channel types (plan 32 / A7a, AC-CHN-03) - never a parallel dialog:
 * WhatsApp picks a number, Messenger/Instagram pick a Page (or its linked
 * Instagram account); a page already bound to a live channel is not offered.
 *
 * Note: in production the number/page is selected *inside Meta's popup* -
 * never typed into a Foundryx form. The "register a number" mode only
 * simulates Meta's WhatsApp registration step so the prototype is
 * self-contained; Messenger/Instagram have no such mode (a Page comes from
 * the user's own Facebook account, D-A7-14).
 */
export function MockEmbeddedSignupDialog({
  open,
  channelType,
  busy,
  onAuthorizeWaba,
  onAuthorizeMeta,
  onCancel,
}: MockEmbeddedSignupDialogProps) {
  const isWhatsApp = channelType === 'WHATSAPP';
  const capabilities = CHANNEL_CAPABILITIES[channelType];
  const Icon = capabilities.icon;

  const [mode, setMode] = useState<'pick' | 'register'>('pick');
  const [selectedId, setSelectedId] = useState<string>(MOCK_WABA_OPTIONS[0]?.wabaId ?? '');
  const [businessName, setBusinessName] = useState('');
  const [phone, setPhone] = useState('');

  const metaOptions = useMemo(
    () => (isWhatsApp ? [] : mockMetaPageOptions(channelType as 'FACEBOOK' | 'INSTAGRAM').filter((p) => !p.connected)),
    [isWhatsApp, channelType],
  );
  const [selectedPageId, setSelectedPageId] = useState<string>('');
  const effectivePageId = selectedPageId || metaOptions[0]?.id || '';

  const selectedWaba = MOCK_WABA_OPTIONS.find((o) => o.wabaId === selectedId);
  const selectedPage = metaOptions.find((o) => o.id === effectivePageId);
  const phoneValid = isValidPhone(phone);
  const showPhoneError = phone.trim().length > 0 && !phoneValid;
  const registerValid = businessName.trim().length > 0 && phoneValid;

  function authorizePicked() {
    if (isWhatsApp) {
      if (selectedWaba) onAuthorizeWaba(selectedWaba);
    } else if (selectedPage) {
      onAuthorizeMeta(selectedPage);
    }
  }

  function authorizeRegistered() {
    if (!registerValid) return;
    const normalized = normalizePhone(phone);
    const id = `new-${normalized.replace(/\D/g, '')}`;
    onAuthorizeWaba({
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
            <span className={cn('flex size-8 items-center justify-center rounded-md', capabilities.accentClassName)}>
              <Icon className="size-4.5" />
            </span>
            <div>
              <DialogTitle>Connect with {capabilities.label}</DialogTitle>
              <DialogDescription className="text-xs">Simulated Meta authorization (sandbox)</DialogDescription>
            </div>
          </div>
        </DialogHeader>

        {mode === 'pick' ? (
          <>
            <DialogBody className="flex flex-col gap-3">
              <p className="text-sm text-muted-foreground">
                {isWhatsApp
                  ? 'Select the WhatsApp Business number to connect to this workspace.'
                  : channelType === 'INSTAGRAM'
                    ? 'Select the Instagram professional account to connect to this workspace.'
                    : 'Select the Facebook Page to connect to this workspace.'}
              </p>

              {isWhatsApp ? (
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
              ) : metaOptions.length === 0 ? (
                <p className="rounded-md border border-dashed p-3 text-sm text-muted-foreground" data-testid="mock-meta-empty">
                  No connectable pages available.
                </p>
              ) : (
                <RadioGroup value={effectivePageId} onValueChange={setSelectedPageId} className="flex flex-col gap-2">
                  {metaOptions.map((opt) => (
                    <label
                      key={opt.id}
                      htmlFor={`page-${opt.id}`}
                      className={cn(
                        'flex cursor-pointer items-center gap-3 rounded-lg border p-3 transition-colors',
                        effectivePageId === opt.id ? 'border-primary bg-primary/5' : 'border-border hover:bg-muted/50',
                      )}
                      data-testid={`mock-meta-page-${opt.id}`}
                    >
                      <RadioGroupItem value={opt.id} id={`page-${opt.id}`} />
                      <span className={cn('flex size-8 items-center justify-center rounded-md', capabilities.accentClassName)}>
                        <Icon className="size-4" />
                      </span>
                      <span className="flex flex-col">
                        <span className="text-sm font-medium text-foreground">
                          {channelType === 'INSTAGRAM' ? (opt.igUsername ?? opt.name) : opt.name}
                        </span>
                        {channelType === 'INSTAGRAM' && (
                          <span className="text-xs text-muted-foreground">Linked to {opt.name}</span>
                        )}
                      </span>
                    </label>
                  ))}
                </RadioGroup>
              )}

              {isWhatsApp && (
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
              )}
            </DialogBody>

            <DialogFooter>
              <Button variant="outline" onClick={onCancel} disabled={busy}>
                Cancel
              </Button>
              <Button
                onClick={authorizePicked}
                disabled={busy || (isWhatsApp ? !selectedWaba : !selectedPage)}
                data-testid="mock-meta-authorize"
              >
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
                  placeholder="e.g. Foundryx VIP Desk"
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
