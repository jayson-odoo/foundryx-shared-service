'use client';

import { Suspense } from 'react';
import { EmailChangeRedeem } from '@/components/auth/email-change-redeem';

/**
 * OLD-side approve page (plan sprint-2/04). Linked from the approval email
 * (`/approve-email-change?token=...`); on approval the verify link goes out
 * to the NEW address. Public - the recipient may not be signed in.
 */
export default function Page() {
  return (
    <Suspense>
      <EmailChangeRedeem kind="approve" />
    </Suspense>
  );
}
