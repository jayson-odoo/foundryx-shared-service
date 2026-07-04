'use client';

import { useState } from 'react';
import {
  emailChangeService,
  EmailTakenError,
  InvalidTokenError,
  RateLimitError,
} from '@/services/email-change-service';
import { throttleMessage } from '@/lib/throttle-message';

export type EmailChangeRedeemKind = 'approve' | 'verify';

export interface UseEmailChangeRedeemResult {
  redeem: (token: string) => Promise<void>;
  isProcessing: boolean;
  isSuccess: boolean;
  error: string | null;
  /** True when the failure was a bad/expired token — show the dead-link state. */
  isTokenError: boolean;
}

/**
 * Drives the public approve/verify token-redeem pages (plan sprint-2/04).
 * `approve` = OLD-side link (moves the request to PENDING_NEW and mails the
 * new address); `verify` = NEW-side link (flips the email). Redeem fires on an
 * explicit button click — single-use tokens must survive mail-scanner
 * prefetches, so the page never redeems on mount.
 */
export function useEmailChangeRedeem(
  kind: EmailChangeRedeemKind,
): UseEmailChangeRedeemResult {
  const [isProcessing, setIsProcessing] = useState(false);
  const [isSuccess, setIsSuccess] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isTokenError, setIsTokenError] = useState(false);

  async function redeem(token: string): Promise<void> {
    setIsProcessing(true);
    setError(null);
    setIsTokenError(false);
    try {
      if (kind === 'approve') {
        await emailChangeService.approve(token);
      } else {
        await emailChangeService.verify(token);
      }
      setIsSuccess(true);
    } catch (err) {
      if (err instanceof InvalidTokenError) {
        setError('This link is invalid or has expired.');
        setIsTokenError(true);
      } else if (err instanceof EmailTakenError) {
        setError(err.message || 'This email address is no longer available.');
      } else if (err instanceof RateLimitError) {
        setError(throttleMessage(err.retryAfterSeconds));
      } else {
        setError('Something went wrong. Please try again.');
      }
    } finally {
      setIsProcessing(false);
    }
  }

  return { redeem, isProcessing, isSuccess, error, isTokenError };
}
