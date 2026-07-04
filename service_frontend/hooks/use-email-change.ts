'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  emailChangeService,
  InvalidPasswordError,
  RateLimitError,
} from '@/services/email-change-service';
import type { PendingEmailChange } from '@/types/account';
import { throttleMessage } from '@/lib/throttle-message';

export interface UseEmailChangeResult {
  /** The outstanding change request (null = none); drives the pending banner. */
  pending: PendingEmailChange | null;
  /** Initial pending-request fetch in flight. */
  isLoading: boolean;
  /** A request/cancel call in flight. */
  isProcessing: boolean;
  error: string | null;
  /**
   * Start the ceremony. Resolves true on success (the dialog flips to its
   * "check your current inbox" state); false leaves `error` set.
   */
  requestChange: (newEmail: string, password: string) => Promise<boolean>;
  /** Cancel the outstanding request. */
  cancelChange: () => Promise<void>;
  clearError: () => void;
}

/**
 * Drives the change-email ceremony from the account page (plan sprint-2/04):
 * loads the caller's outstanding request, starts a new one (password
 * re-entry), cancels. Approve/verify redeems live in use-email-change-redeem
 * (public pages).
 */
export function useEmailChange(): UseEmailChangeResult {
  const [pending, setPending] = useState<PendingEmailChange | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isProcessing, setIsProcessing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    emailChangeService
      .getPending()
      .then((row) => {
        if (!cancelled) setPending(row);
      })
      .catch(() => {
        // Banner is best-effort — a failed status read never blocks the page.
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const requestChange = useCallback(
    async (newEmail: string, password: string): Promise<boolean> => {
      setIsProcessing(true);
      setError(null);
      try {
        const row = await emailChangeService.request(newEmail, password);
        setPending(row);
        return true;
      } catch (err) {
        if (err instanceof InvalidPasswordError) {
          setError(err.message || 'Incorrect password.');
        } else if (err instanceof RateLimitError) {
          setError(throttleMessage(err.retryAfterSeconds));
        } else {
          setError('Something went wrong. Please try again.');
        }
        return false;
      } finally {
        setIsProcessing(false);
      }
    },
    [],
  );

  const cancelChange = useCallback(async (): Promise<void> => {
    setIsProcessing(true);
    setError(null);
    try {
      await emailChangeService.cancel();
      setPending(null);
    } catch {
      setError('Something went wrong. Please try again.');
    } finally {
      setIsProcessing(false);
    }
  }, []);

  const clearError = useCallback(() => setError(null), []);

  return {
    pending,
    isLoading,
    isProcessing,
    error,
    requestChange,
    cancelChange,
    clearError,
  };
}
