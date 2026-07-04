'use client';

import { useState } from 'react';
import { passwordService, RateLimitError } from '@/services/password-service';
import { throttleMessage } from '@/lib/throttle-message';

export interface UseForgotPasswordResult {
  requestReset: (email: string) => Promise<void>;
  isProcessing: boolean;
  /** The uniform enumeration-safe confirmation, once the request succeeds. */
  successMessage: string | null;
  error: string | null;
  clearError: () => void;
}

/**
 * Drives the forgot-password request flow (plan 10 §3): calls the password
 * service, tracks loading/success/error. The page never talks to the service
 * directly (UI → hook → service → backend).
 */
export function useForgotPassword(): UseForgotPasswordResult {
  const [isProcessing, setIsProcessing] = useState(false);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function requestReset(email: string): Promise<void> {
    setIsProcessing(true);
    setError(null);
    try {
      const { message } = await passwordService.requestReset(email);
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
