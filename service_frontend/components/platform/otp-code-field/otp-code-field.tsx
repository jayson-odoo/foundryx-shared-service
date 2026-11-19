'use client';

import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { LoaderCircleIcon } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

/**
 * One-time code field mirroring the Sorento CRM portal / sign-in code field
 * (`components/auth/OtpCodeField.tsx`, lane FEEDBACK-SHARE-SS-HOST, owner
 * 19 Nov): ONE numeric field, no Verify button - it completes on its own on
 * the 6th digit; below it a full-width resend button with a countdown, or a
 * status row while the code is being checked. After a failed check the field
 * unlocks and takes focus again.
 */
export const OTP_LENGTH = 6;

export interface OtpCodeFieldProps {
  value: string;
  onChange: (value: string) => void;
  /** Fires once per distinct 6-digit value, only when sent && !pending && !disabled. */
  onComplete: (code: string) => void;
  /** Seconds left before resend is enabled; 0 = enabled. */
  cooldown: number;
  /** "Send code" vs "Resend code". */
  sent: boolean;
  pending: boolean;
  disabled?: boolean;
  onResend: () => void;
  id?: string;
  autoFocus?: boolean;
  /** Replaces the resend button (e.g. "Signing you in as ..."). */
  status?: ReactNode;
  /** Send code is the filled primary button until a code has gone. */
  primarySend?: boolean;
}

export function OtpCodeField({
  value,
  onChange,
  onComplete,
  cooldown,
  sent,
  pending,
  disabled = false,
  onResend,
  id = 'otp-code',
  autoFocus = false,
  status,
  primarySend = false,
}: OtpCodeFieldProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const completedRef = useRef<string | null>(null);
  const wasPending = useRef(pending);

  useEffect(() => {
    if (value.length < OTP_LENGTH) completedRef.current = null;
    if (value.length !== OTP_LENGTH || !sent || pending || disabled) return;
    if (completedRef.current === value) return;
    completedRef.current = value;
    onComplete(value);
  }, [value, sent, pending, disabled, onComplete]);

  // Unlock: once a check ends, hand focus back to the field.
  useEffect(() => {
    if (wasPending.current && !pending && !disabled) inputRef.current?.focus();
    wasPending.current = pending;
  }, [pending, disabled]);

  const label = cooldown > 0 ? `Resend in ${cooldown}s` : sent ? 'Resend code' : 'Send code';

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-2">
        <Label htmlFor={id}>Verification code</Label>
        <Input
          ref={inputRef}
          id={id}
          inputMode="numeric"
          maxLength={OTP_LENGTH}
          placeholder="6-digit code"
          autoComplete="one-time-code"
          autoFocus={autoFocus}
          disabled={pending || disabled}
          value={value}
          onChange={(e) => onChange(e.target.value.replace(/\D/g, '').slice(0, OTP_LENGTH))}
          className="text-center tracking-[0.4em] text-lg font-medium"
        />
      </div>
      {status ? (
        <div role="status" className="flex h-11 items-center justify-center gap-2 text-sm text-muted-foreground">
          <LoaderCircleIcon aria-hidden className="size-4 animate-spin" />
          {status}
        </div>
      ) : (
        <Button
          type="button"
          variant={primarySend && !sent ? 'primary' : 'outline'}
          className="h-11 w-full"
          disabled={pending || disabled || cooldown > 0}
          onClick={onResend}
        >
          {label}
        </Button>
      )}
    </div>
  );
}

export interface ResendCooldown {
  seconds: number;
  start: (seconds: number) => void;
}

/** Seconds left before the code may be sent again, ticking once a second. */
export function useResendCooldown(): ResendCooldown {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    if (seconds <= 0) return undefined;
    const t = setTimeout(() => setSeconds((s) => Math.max(0, s - 1)), 1000);
    return () => clearTimeout(t);
  }, [seconds]);
  const start = useCallback((n: number) => setSeconds(Math.max(0, Math.floor(n))), []);
  return { seconds, start };
}
