'use client';

import { Suspense } from 'react';
import { EmailChangeRedeem } from '@/components/auth/email-change-redeem';

/**
 * NEW-side verify page (plan sprint-2/04). Linked from the verification email
 * (`/verify-email-change?token=...`); this redeem is the step that actually
 * flips the account email. Public — the recipient may not be signed in.
 */
export default function Page() {
  return (
    <Suspense>
      <EmailChangeRedeem kind="verify" />
    </Suspense>
  );
}
