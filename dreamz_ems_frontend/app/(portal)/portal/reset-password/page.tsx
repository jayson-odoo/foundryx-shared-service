'use client';

import Link from 'next/link';
import { zodResolver } from '@hookform/resolvers/zod';
import {
  AlertCircle,
  ArrowLeft,
  LoaderCircleIcon,
  MailCheck,
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
import { usePortalForgotPassword } from '@/hooks/use-portal-forgot-password';
import { PortalAuthShell } from '../login/portal-auth-shell';
import {
  getPortalForgotPasswordSchema,
  type PortalForgotPasswordSchemaType,
} from '../forms/portal-password-schema';

/**
 * Portal forgot-password request page (AC-06-15b). Public; posts the email
 * through use-portal-forgot-password → portal-auth-service →
 * POST /portal/auth/forgot-password and shows the uniform enumeration-safe
 * confirmation either way.
 */
export default function Page() {
  const { requestReset, isProcessing, successMessage, error } =
    usePortalForgotPassword();

  const form = useForm<PortalForgotPasswordSchemaType>({
    resolver: zodResolver(getPortalForgotPasswordSchema()),
    defaultValues: { email: '' },
  });

  async function onSubmit(values: PortalForgotPasswordSchemaType) {
    await requestReset(values.email);
  }

  if (successMessage) {
    return (
      <PortalAuthShell>
        <div className="block w-full space-y-6">
          <div className="space-y-2">
            <h1 className="font-heading text-3xl font-semibold tracking-tight text-mono">
              Check your email.
            </h1>
            <p className="font-heading text-base font-medium text-muted-foreground">
              {successMessage}
            </p>
          </div>
          <Alert>
            <AlertIcon>
              <MailCheck />
            </AlertIcon>
            <AlertTitle>
              The link expires soon — use it as quickly as you can.
            </AlertTitle>
          </Alert>
          <Button variant="outline" className="w-full" asChild>
            <Link href="/portal/login">
              <ArrowLeft className="size-3.5" /> Back to Sign In
            </Link>
          </Button>
        </div>
      </PortalAuthShell>
    );
  }

  return (
    <PortalAuthShell>
      <Form {...form}>
        <form
          onSubmit={form.handleSubmit(onSubmit)}
          className="block w-full space-y-6"
        >
          <div className="space-y-2">
            <h1 className="font-heading text-3xl font-semibold tracking-tight text-mono">
              Forgot your password?
            </h1>
            <p className="font-heading text-base font-medium text-muted-foreground">
              Enter your email and we&apos;ll send you a reset link.
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
            name="email"
            render={({ field }) => (
              <FormItem>
                <FormLabel className="font-heading font-semibold">
                  Email
                </FormLabel>
                <FormControl>
                  <Input placeholder="Your email" {...field} />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

          <Button type="submit" className="w-full" disabled={isProcessing}>
            {isProcessing ? (
              <LoaderCircleIcon className="size-4 animate-spin" />
            ) : null}
            Send Reset Link
          </Button>

          <Button type="button" variant="outline" className="w-full" asChild>
            <Link href="/portal/login">
              <ArrowLeft className="size-3.5" /> Back to Sign In
            </Link>
          </Button>
        </form>
      </Form>
    </PortalAuthShell>
  );
}
