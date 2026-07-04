'use client';

import { useState } from 'react';
import {
  portalAuthService,
  RateLimitError,
} from '@/services/portal-auth-service';
import { throttleMessage } from '@/lib/throttle-message';

export interface UsePortalForgotPasswordResult {
  requestReset: (email: string) => Promise<void>;
  isProcessing: boolean;
  /** The uniform enumeration-safe confirmation, once the request succeeds. */
  successMessage: string | null;
  error: string | null;
  clearError: () => void;
}

/**
 * Drives the portal forgot-password request flow (AC-06-15b): calls the portal
 * auth service, tracks loading/success/error, surfaces the uniform
 * enumeration-safe confirmation either way.
 */
export function usePortalForgotPassword(): UsePortalForgotPasswordResult {
  const [isProcessing, setIsProcessing] = useState(false);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function requestReset(email: string): Promise<void> {
    setIsProcessing(true);
    setError(null);
    try {
      const { message } = await portalAuthService.requestReset(email);
      setSuccessMessage(message);
    } catch (err) {
      setError(
        err instanceof RateLimitError
          ? throttleMessage(err.retryAfterSeconds)
          : 'Something went wrong. Please try again.',
      );
    } finally {
      setIsProcessing(false);
    }
  }

  return {
    requestReset,
    isProcessing,
    successMessage,
    error,
    clearError: () => setError(null),
  };
}
