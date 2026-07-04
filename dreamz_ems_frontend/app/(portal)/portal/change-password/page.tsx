'use client';

import { Suspense, useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { zodResolver } from '@hookform/resolvers/zod';
import {
  AlertCircle,
  Check,
  Eye,
  EyeOff,
  LoaderCircleIcon,
} from 'lucide-react';
import { useForm } from 'react-hook-form';
import { Alert, AlertIcon, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { usePortalChangePassword } from '@/hooks/use-portal-change-password';
import { PortalAuthShell } from '../login/portal-auth-shell';
import {
  getPortalChangePasswordSchema,
  type PortalChangePasswordSchemaType,
} from '../forms/portal-password-schema';

/**
 * Portal set/change-password (token redeem) page (AC-06-15a). Linked from the
 * invite / reset email (`/portal/change-password?token=...`). Redeems via
 * use-portal-change-password → portal-auth-service → POST /portal/auth/set-password.
 * Redeem fires on EXPLICIT submit only — a mail-scanner prefetch must never
 * consume the single-use token (AC-06-17).
 */
function PortalChangePasswordForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams?.get('token') ?? '';

  const { changePassword, isProcessing, isSuccess, error, isTokenError } =
    usePortalChangePassword();
  const [passwordVisible, setPasswordVisible] = useState(false);
  const [confirmVisible, setConfirmVisible] = useState(false);

  const form = useForm<PortalChangePasswordSchemaType>({
    resolver: zodResolver(getPortalChangePasswordSchema()),
    defaultValues: { newPassword: '', confirmPassword: '' },
  });

  useEffect(() => {
    if (!isSuccess) return;
    const redirect = setTimeout(() => router.push('/portal/login'), 3000);
    return () => clearTimeout(redirect);
  }, [isSuccess, router]);

  async function onSubmit(values: PortalChangePasswordSchemaType) {
    await changePassword(token, values.newPassword);
  }

  if (isSuccess) {
    return (
      <div className="block w-full space-y-6">
        <div className="space-y-2">
          <h1 className="font-heading text-3xl font-semibold tracking-tight text-mono">
            Password set.
          </h1>
          <p className="font-heading text-base font-medium text-muted-foreground">
            Your password is ready. Redirecting you to sign in…
          </p>
        </div>
        <Alert>
          <AlertIcon>
            <Check />
          </AlertIcon>
          <AlertTitle>Sign in with your new password.</AlertTitle>
        </Alert>
        <Button className="w-full" asChild>
          <Link href="/portal/login">Go to Sign In</Link>
        </Button>
      </div>
    );
  }

  if (!token || isTokenError) {
    return (
      <div className="block w-full space-y-6">
        <div className="space-y-2">
          <h1 className="font-heading text-3xl font-semibold tracking-tight text-mono">
            Link expired.
          </h1>
          <p className="font-heading text-base font-medium text-muted-foreground">
            This link is invalid or has expired.
          </p>
        </div>
        <Alert variant="destructive">
          <AlertIcon>
            <AlertCircle />
          </AlertIcon>
          <AlertTitle>
            These links are single-use and expire after a short while.
          </AlertTitle>
        </Alert>
        <Button className="w-full" asChild>
          <Link href="/portal/reset-password">Request a New Link</Link>
        </Button>
      </div>
    );
  }

  return (
    <Form {...form}>
      <form
        onSubmit={form.handleSubmit(onSubmit)}
        className="block w-full space-y-6"
      >
        <div className="space-y-2">
          <h1 className="font-heading text-3xl font-semibold tracking-tight text-mono">
            Set a password.
          </h1>
          <p className="font-heading text-base font-medium text-muted-foreground">
            Use at least 8 characters with upper &amp; lower case letters, a
            number and a special character.
          </p>
        </div>

        {error && (
          <Alert variant="destructive">
            <AlertIcon>
              <AlertCircle />
            </AlertIcon>
            <AlertTitle>{error}</AlertTitle>
          </Alert>
        )}

        <FormField
          control={form.control}
          name="newPassword"
          render={({ field }) => (
            <FormItem>
              <FormLabel className="font-heading font-semibold">
                New Password
              </FormLabel>
              <div className="relative">
                <FormControl>
                  <Input
                    placeholder="Your new password"
                    type={passwordVisible ? 'text' : 'password'}
                    {...field}
                  />
                </FormControl>
                <Button
                  type="button"
                  variant="ghost"
                  mode="icon"
                  size="sm"
                  onClick={() => setPasswordVisible(!passwordVisible)}
                  className="absolute end-0 top-1/2 me-1.5 h-7 w-7 -translate-y-1/2 bg-transparent!"
                  aria-label={passwordVisible ? 'Hide password' : 'Show password'}
                >
                  {passwordVisible ? (
                    <EyeOff className="text-muted-foreground" />
                  ) : (
                    <Eye className="text-muted-foreground" />
                  )}
                </Button>
              </div>
              <FormMessage />
            </FormItem>
          )}
        />

        <FormField
          control={form.control}
          name="confirmPassword"
          render={({ field }) => (
            <FormItem>
              <FormLabel className="font-heading font-semibold">
                Confirm New Password
              </FormLabel>
              <div className="relative">
                <FormControl>
                  <Input
                    placeholder="Confirm your new password"
                    type={confirmVisible ? 'text' : 'password'}
                    {...field}
                  />
                </FormControl>
                <Button
                  type="button"
                  variant="ghost"
                  mode="icon"
                  size="sm"
                  onClick={() => setConfirmVisible(!confirmVisible)}
                  className="absolute end-0 top-1/2 me-1.5 h-7 w-7 -translate-y-1/2 bg-transparent!"
                  aria-label={
                    confirmVisible
                      ? 'Hide password confirmation'
                      : 'Show password confirmation'
                  }
                >
                  {confirmVisible ? (
                    <EyeOff className="text-muted-foreground" />
                  ) : (
                    <Eye className="text-muted-foreground" />
                  )}
                </Button>
              </div>
              <FormMessage />
            </FormItem>
          )}
        />

        <Button type="submit" className="w-full" disabled={isProcessing}>
          {isProcessing ? (
            <LoaderCircleIcon className="size-4 animate-spin" />
          ) : null}
          Set Password
        </Button>
      </form>
    </Form>
  );
}

export default function Page() {
  return (
    <PortalAuthShell>
      <Suspense>
        <PortalChangePasswordForm />
      </Suspense>
    </PortalAuthShell>
  );
}
