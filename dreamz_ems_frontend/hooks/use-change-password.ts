'use client';

import { useState } from 'react';
import {
  InvalidTokenError,
  passwordService,
  RateLimitError,
} from '@/services/password-service';
import { throttleMessage } from '@/lib/throttle-message';

export interface UseChangePasswordResult {
  changePassword: (token: string, password: string) => Promise<void>;
  isProcessing: boolean;
  isSuccess: boolean;
  error: string | null;
  /** True when the failure was a bad/expired token — offer "request a new link". */
  isTokenError: boolean;
  clearError: () => void;
}

/**
 * Drives the change-password (token redeem) flow (plan 10 §3): calls the
 * password service, tracks loading/success/error. Invalid/expired tokens get
 * a distinct flag so the page can offer a fresh reset link.
 */
export function useChangePassword(): UseChangePasswordResult {
  const [isProcessing, setIsProcessing] = useState(false);
  const [isSuccess, setIsSuccess] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isTokenError, setIsTokenError] = useState(false);

  async function changePassword(token: string, password: string): Promise<void> {
    setIsProcessing(true);
    setError(null);
    setIsTokenError(false);
    try {
      await passwordService.setPassword(token, password);
      setIsSuccess(true);
    } catch (err) {
      if (err instanceof InvalidTokenError) {
        setError('This reset link is invalid or has expired.');
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
