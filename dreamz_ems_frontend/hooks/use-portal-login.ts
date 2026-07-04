'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  portalAuthService,
  PortalAuthError,
  RateLimitError,
  type PortalOtpCredentials,
  type PortalPasswordCredentials,
} from '@/services/portal-auth-service';
import { throttleMessage } from '@/lib/throttle-message';

export interface UsePortalLoginResult {
  /** Password login → portal session, then redirect on success. */
  signin: (credentials: PortalPasswordCredentials) => Promise<void>;
  /** Request an emailed verification code (OTP). Surfaces the uniform message. */
  requestOtp: (email: string) => Promise<void>;
  /** OTP login → portal session, then redirect on success. */
  signinOtp: (credentials: PortalOtpCredentials) => Promise<void>;
  isProcessing: boolean;
  /** True once a code has been requested (drives the OTP "enter code" step). */
  otpRequested: boolean;
  /** Uniform enumeration-safe confirmation after requesting a code. */
  otpMessage: string | null;
  error: string | null;
  clearError: () => void;
  /** Reset back to the email step of the OTP flow. */
  resetOtp: () => void;
}

/**
 * Drives the portal login flow (AC-06-12): password primary + email
 * verification-code (OTP) fallback. The page never talks to the service
 * directly (UI → hook → service → portal-api-client).
 */
export function usePortalLogin(redirectTo = '/portal/dashboard'): UsePortalLoginResult {
  const router = useRouter();
  const [isProcessing, setIsProcessing] = useState(false);
  const [otpRequested, setOtpRequested] = useState(false);
  const [otpMessage, setOtpMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  function mapError(err: unknown): string {
    if (err instanceof PortalAuthError) return err.message;
    if (err instanceof RateLimitError) {
      return throttleMessage(err.retryAfterSeconds);
    }
    return 'Something went wrong. Please try again.';
  }

  async function signin(credentials: PortalPasswordCredentials): Promise<void> {
    setIsProcessing(true);
    setError(null);
    try {
      await portalAuthService.signin(credentials);
      router.push(redirectTo);
    } catch (err) {
      setError(mapError(err));
      setIsProcessing(false);
    }
  }

  async function requestOtp(email: string): Promise<void> {
    setIsProcessing(true);
    setError(null);
    try {
      const { message } = await portalAuthService.requestOtp(email);
      setOtpMessage(message);
      setOtpRequested(true);
    } catch (err) {
      setError(mapError(err));
    } finally {
      setIsProcessing(false);
    }
  }

  async function signinOtp(credentials: PortalOtpCredentials): Promise<void> {
    setIsProcessing(true);
    setError(null);
    try {
      await portalAuthService.signinOtp(credentials);
      router.push(redirectTo);
    } catch (err) {
      setError(mapError(err));
      setIsProcessing(false);
    }
  }

  return {
    signin,
    requestOtp,
    signinOtp,
    isProcessing,
    otpRequested,
    otpMessage,
    error,
    clearError: () => setError(null),
    resetOtp: () => {
      setOtpRequested(false);
      setOtpMessage(null);
      setError(null);
    },
  };
}
