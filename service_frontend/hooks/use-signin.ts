'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  authService,
  AuthError,
  type SigninCredentials,
} from '@/services/auth-service';

export interface UseSigninResult {
  signin: (credentials: SigninCredentials) => Promise<void>;
  isProcessing: boolean;
  error: string | null;
  clearError: () => void;
}

/**
 * Drives the sign-in flow for the UI: calls the auth service, tracks
 * loading/error state, and redirects on success. The page never talks to the
 * service directly (UI → hook → service → backend).
 */
export function useSignin(redirectTo = '/'): UseSigninResult {
  const router = useRouter();
  const [isProcessing, setIsProcessing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function signin(credentials: SigninCredentials): Promise<void> {
    setIsProcessing(true);
    setError(null);
    try {
      await authService.signin(credentials);
      router.push(redirectTo);
    } catch (err) {
      setError(
        err instanceof AuthError
          ? err.message
          : 'Something went wrong. Please try again.',
      );
      setIsProcessing(false); // stay on the page so the user can retry
    }
  }

  return {
    signin,
    isProcessing,
    error,
    clearError: () => setError(null),
  };
}
