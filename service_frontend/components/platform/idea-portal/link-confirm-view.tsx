'use client';

import { useState, type FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import { useLinkSignIn, PORTAL_PATHS } from '@/hooks/use-idea-portal';
import { BrandMark } from '@/components/platform/branding';
import { useTenantBranding } from '@/hooks/use-branding';
import { usePublicPageBranding } from '@/app/(public)/public-branded-shell';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

export interface LinkConfirmViewProps {
  token: string;
}

/** Q1 (b): the chatbot link + the last 4 digits of the dealer's WhatsApp
 * number signs them in, then opens the idea in the portal. */
export function LinkConfirmView({ token }: LinkConfirmViewProps) {
  const router = useRouter();
  const { confirm, submitting, error } = useLinkSignIn(token);
  const [last4, setLast4] = useState('');
  const shellBranding = usePublicPageBranding();
  const { branding: live } = useTenantBranding();
  const branding = shellBranding ?? live;
  const valid = /^[0-9]{4}$/.test(last4);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!valid || submitting) return;
    const ideaId = await confirm(last4);
    if (ideaId) router.replace(PORTAL_PATHS.idea(ideaId));
  };

  return (
    <div className="mx-auto mt-16 w-full max-w-sm px-4" data-testid="portal-link-confirm">
      <Card>
        <CardContent className="py-6">
          <form className="flex flex-col gap-4" onSubmit={onSubmit}>
            <BrandMark branding={branding} />
            <h1 className="font-heading text-lg font-semibold">Confirm it’s you</h1>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="portal-last4">
                Last 4 digits of your WhatsApp number<span className="text-primary"> *</span>
              </Label>
              <Input
                id="portal-last4"
                inputMode="numeric"
                autoComplete="off"
                maxLength={4}
                value={last4}
                onChange={(e) => setLast4(e.target.value.replace(/\D/g, '').slice(0, 4))}
              />
            </div>
            {error && (
              <p className="text-sm text-destructive" role="alert">
                {error}
              </p>
            )}
            <Button type="submit" disabled={!valid || submitting}>
              {submitting ? 'Checking…' : 'Continue'}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
