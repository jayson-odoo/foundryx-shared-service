'use client';

import { useState } from 'react';
import {
  InvalidTokenError,
  portalAuthService,
  RateLimitError,
} from '@/services/portal-auth-service';
import { throttleMessage } from '@/lib/throttle-message';

export interface UsePortalChangePasswordResult {
  changePassword: (token: string, password: string) => Promise<void>;
  isProcessing: boolean;
  isSuccess: boolean;
  error: string | null;
  /** True when the failure was a bad/expired token — offer "request a new link". */
  isTokenError: boolean;
  clearError: () => void;
}

/**
 * Drives the portal set/change-password (token redeem) flow (AC-06-15a). Redeem
 * fires only on explicit submit (the page must never auto-fire on mount — a
 * mail-scanner prefetch must not consume the single-use token, AC-06-17).
 */
export function usePortalChangePassword(): UsePortalChangePasswordResult {
  const [isProcessing, setIsProcessing] = useState(false);
  const [isSuccess, setIsSuccess] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isTokenError, setIsTokenError] = useState(false);

  async function changePassword(
    token: string,
    password: string,
  ): Promise<void> {
    setIsProcessing(true);
    setError(null);
    setIsTokenError(false);
    try {
      await portalAuthService.setPassword(token, password);
      setIsSuccess(true);
    } catch (err) {
      if (err instanceof InvalidTokenError) {
        setError('This link is invalid or has expired.');
        setIsTokenError(true);
      } else if (err instanceof RateLimitError) {
        setError(throttleMessage(err.retryAfterSeconds));
      } else {
        setError('Something went wrong. Please try again.');
      }
    } finally {
      setIsProcessing(false);
    }
  }

  return {
    changePassword,
    isProcessing,
    isSuccess,
    error,
    isTokenError,
    clearError: () => setError(null),
  };
}
