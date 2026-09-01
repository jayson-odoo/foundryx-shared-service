'use client';

import Link from 'next/link';
import { AlertCircle, Check, LoaderCircleIcon } from 'lucide-react';
import { useSearchParams } from 'next/navigation';
import { Alert, AlertIcon, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import {
  useEmailChangeRedeem,
  type EmailChangeRedeemKind,
} from '@/hooks/use-email-change-redeem';

/** Per-kind copy - approve = OLD-side link, verify = NEW-side link. */
const COPY: Record<
  EmailChangeRedeemKind,
  {
    heading: string;
    description: string;
    action: string;
    successHeading: string;
    successBody: string;
  }
> = {
  approve: {
    heading: 'Approve email change',
    description:
      'Someone asked to change the email on your account. Approve only if this was you - if not, just close this page and the request will expire.',
    action: 'Approve Change',
    successHeading: 'Change approved.',
    successBody:
      'One step left: open the inbox of your NEW address and confirm it from the link we just sent. Your email stays unchanged until then.',
  },
  verify: {
    heading: 'Confirm your new email',
    description:
      'Confirm that this mailbox is yours - this is the step that switches your account to the new address.',
    action: 'Confirm New Email',
    successHeading: 'Email updated.',
    successBody: 'From now on, sign in with your new email address.',
  },
};

/**
 * Shared body of the public approve/verify email-change pages (plan
 * sprint-2/04). Redeems on an explicit click - never on mount - so
 * mail-scanner prefetches can't burn the single-use token.
 */
export function EmailChangeRedeem({ kind }: { kind: EmailChangeRedeemKind }) {
  const searchParams = useSearchParams();
  const token = searchParams?.get('token') ?? '';
  const { redeem, isProcessing, isSuccess, error, isTokenError } =
    useEmailChangeRedeem(kind);
  const copy = COPY[kind];

  if (isSuccess) {
    return (
      <div className="block w-full space-y-6">
        <div className="space-y-2">
          <h1 className="font-heading text-3xl font-semibold tracking-tight text-mono">
            {copy.successHeading}
          </h1>
          <p className="font-heading text-base font-medium text-muted-foreground">
            {copy.successBody}
          </p>
        </div>
        <Alert>
          <AlertIcon>
            <Check />
          </AlertIcon>
          <AlertTitle>
            {kind === 'verify'
              ? 'A notice was also sent to your previous address.'
              : 'You can close this page.'}
          </AlertTitle>
        </Alert>
        {kind === 'verify' && (
          <Button className="w-full" asChild>
            <Link href="/signin">Go to Sign In</Link>
          </Button>
        )}
      </div>
    );
  }

  // Missing token or a redeem that failed on the token itself: dead-link
  // state + the way back (a fresh request starts from the account page).
  if (!token || isTokenError) {
    return (
      <div className="block w-full space-y-6">
        <div className="space-y-2">
          <h1 className="font-heading text-3xl font-semibold tracking-tight text-mono">
            Link expired.
          </h1>
          <p className="font-heading text-base font-medium text-muted-foreground">
            This link is invalid or has expired.
          </p>
        </div>
        <Alert variant="destructive">
          <AlertIcon>
            <AlertCircle />
          </AlertIcon>
          <AlertTitle>
            Email-change links are single-use and expire after a short while.
            Start a new request from your account page.
          </AlertTitle>
        </Alert>
        <Button className="w-full" asChild>
          <Link href="/account">Go to My Account</Link>
        </Button>
      </div>
    );
  }

  return (
    <div className="block w-full space-y-6">
      <div className="space-y-2">
        <h1 className="font-heading text-3xl font-semibold tracking-tight text-mono">
          {copy.heading}
        </h1>
        <p className="font-heading text-base font-medium text-muted-foreground">
          {copy.description}
        </p>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertIcon>
            <AlertCircle />
          </AlertIcon>
          <AlertTitle>{error}</AlertTitle>
        </Alert>
      )}

      <Button
        className="w-full"
        onClick={() => redeem(token)}
        disabled={isProcessing}
      >
        {isProcessing ? (
          <LoaderCircleIcon className="size-4 animate-spin" />
        ) : null}
        {copy.action}
      </Button>
    </div>
  );
}
