'use client';

import { useState } from 'react';
import Link from 'next/link';
import { zodResolver } from '@hookform/resolvers/zod';
import {
  AlertCircle,
  ArrowLeft,
  Eye,
  EyeOff,
  LoaderCircleIcon,
  MailCheck,
} from 'lucide-react';
import { useForm } from 'react-hook-form';
import { Alert, AlertIcon, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { usePortalLogin } from '@/hooks/use-portal-login';
import { useTenantBranding } from '@/hooks/use-branding';
import { PortalAuthShell } from './portal-auth-shell';
import {
  getPortalLoginSchema,
  getPortalOtpCodeSchema,
  getPortalOtpEmailSchema,
  type PortalLoginSchemaType,
  type PortalOtpCodeSchemaType,
  type PortalOtpEmailSchemaType,
} from '../forms/portal-login-schema';

type Mode = 'password' | 'otp';

export default function Page() {
  const [mode, setMode] = useState<Mode>('password');
  const [passwordVisible, setPasswordVisible] = useState(false);
  const {
    signin,
    requestOtp,
    signinOtp,
    isProcessing,
    otpRequested,
    otpMessage,
    error,
    clearError,
    resetOtp,
  } = usePortalLogin();

  const { branding } = useTenantBranding();
  const welcomeName = branding.appName || branding.tenantName;

  const passwordForm = useForm<PortalLoginSchemaType>({
    resolver: zodResolver(getPortalLoginSchema()),
    defaultValues: { email: '', password: '', rememberMe: false },
  });

  const otpEmailForm = useForm<PortalOtpEmailSchemaType>({
    resolver: zodResolver(getPortalOtpEmailSchema()),
    defaultValues: { email: '', rememberMe: false },
  });

  const otpCodeForm = useForm<PortalOtpCodeSchemaType>({
    resolver: zodResolver(getPortalOtpCodeSchema()),
    defaultValues: { code: '' },
  });

  function switchMode(next: Mode) {
    clearError();
    resetOtp();
    setMode(next);
  }

  async function onPasswordSubmit(values: PortalLoginSchemaType) {
    await signin(values);
  }

  async function onOtpEmailSubmit(values: PortalOtpEmailSchemaType) {
    await requestOtp(values.email);
  }

  async function onOtpCodeSubmit(values: PortalOtpCodeSchemaType) {
    await signinOtp({
      email: otpEmailForm.getValues('email'),
      code: values.code,
      rememberMe: otpEmailForm.getValues('rememberMe'),
    });
  }

  const heading = welcomeName ? `Welcome to ${welcomeName}.` : 'Welcome.';

  return (
    <PortalAuthShell>
      <div className="block w-full space-y-6">
        <div className="space-y-2">
          <h1 className="font-heading text-3xl font-semibold tracking-tight text-mono">
            {heading}
          </h1>
          <p className="font-heading text-base font-medium text-muted-foreground">
            {mode === 'password'
              ? 'Sign in to your account.'
              : 'Sign in with an email code.'}
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

        {mode === 'password' && (
          <Form {...passwordForm}>
            <form
              onSubmit={passwordForm.handleSubmit(onPasswordSubmit)}
              className="block w-full space-y-6"
            >
              <FormField
                control={passwordForm.control}
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

              <FormField
                control={passwordForm.control}
                name="password"
                render={({ field }) => (
                  <FormItem>
                    <div className="flex items-center justify-between gap-2.5">
                      <FormLabel className="font-heading font-semibold">
                        Password
                      </FormLabel>
                      <Link
                        href="/portal/reset-password"
                        className="font-heading text-sm font-semibold text-primary hover:text-primary-active"
                      >
                        Forgot Password?
                      </Link>
                    </div>
                    <div className="relative">
                      <Input
                        placeholder="Your password"
                        type={passwordVisible ? 'text' : 'password'}
                        {...field}
                      />
                      <Button
                        type="button"
                        variant="ghost"
                        mode="icon"
                        size="sm"
                        onClick={() => setPasswordVisible(!passwordVisible)}
                        className="absolute end-0 top-1/2 me-1.5 h-7 w-7 -translate-y-1/2 bg-transparent!"
                        aria-label={
                          passwordVisible ? 'Hide password' : 'Show password'
                        }
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
                control={passwordForm.control}
                name="rememberMe"
                render={({ field }) => (
                  <FormItem className="flex flex-row items-center gap-2.5 space-y-0">
                    <FormControl>
                      <Checkbox
                        checked={field.value ?? false}
                        onCheckedChange={(checked) =>
                          field.onChange(checked === true)
                        }
                        aria-label="Remember me"
                      />
                    </FormControl>
                    <FormLabel className="font-heading text-sm font-medium text-muted-foreground">
                      Remember me
                    </FormLabel>
                  </FormItem>
                )}
              />

              <Button
                type="submit"
                className="w-full"
                disabled={isProcessing}
              >
                {isProcessing ? (
                  <LoaderCircleIcon className="size-4 animate-spin" />
                ) : null}
                Sign In
              </Button>

              <Button
                type="button"
                variant="outline"
                className="w-full"
                onClick={() => switchMode('otp')}
              >
                Sign in with email code
              </Button>
            </form>
          </Form>
        )}

        {mode === 'otp' && !otpRequested && (
          <Form {...otpEmailForm}>
            <form
              onSubmit={otpEmailForm.handleSubmit(onOtpEmailSubmit)}
              className="block w-full space-y-6"
            >
              <FormField
                control={otpEmailForm.control}
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

              <FormField
                control={otpEmailForm.control}
                name="rememberMe"
                render={({ field }) => (
                  <FormItem className="flex flex-row items-center gap-2.5 space-y-0">
                    <FormControl>
                      <Checkbox
                        checked={field.value ?? false}
                        onCheckedChange={(checked) =>
                          field.onChange(checked === true)
                        }
                        aria-label="Remember me"
                      />
                    </FormControl>
                    <FormLabel className="font-heading text-sm font-medium text-muted-foreground">
                      Remember me
                    </FormLabel>
                  </FormItem>
                )}
              />

              <Button
                type="submit"
                className="w-full"
                disabled={isProcessing}
              >
                {isProcessing ? (
                  <LoaderCircleIcon className="size-4 animate-spin" />
                ) : null}
                Send Code
              </Button>

              <Button
                type="button"
                variant="outline"
                className="w-full"
                onClick={() => switchMode('password')}
              >
                <ArrowLeft className="size-3.5" /> Back to password
              </Button>
            </form>
          </Form>
        )}

        {mode === 'otp' && otpRequested && (
          <Form {...otpCodeForm}>
            <form
              onSubmit={otpCodeForm.handleSubmit(onOtpCodeSubmit)}
              className="block w-full space-y-6"
            >
              {otpMessage && (
                <Alert>
                  <AlertIcon>
                    <MailCheck />
                  </AlertIcon>
                  <AlertTitle>{otpMessage}</AlertTitle>
                </Alert>
              )}

              <FormField
                control={otpCodeForm.control}
                name="code"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel className="font-heading font-semibold">
                      Verification code
                    </FormLabel>
                    <FormControl>
                      <Input
                        placeholder="6-digit code"
                        inputMode="numeric"
                        autoComplete="one-time-code"
                        maxLength={6}
                        {...field}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <Button
                type="submit"
                className="w-full"
                disabled={isProcessing}
              >
                {isProcessing ? (
                  <LoaderCircleIcon className="size-4 animate-spin" />
                ) : null}
                Verify &amp; Sign In
              </Button>

              <Button
                type="button"
                variant="outline"
                className="w-full"
                onClick={resetOtp}
              >
                <ArrowLeft className="size-3.5" /> Use a different email
              </Button>
            </form>
          </Form>
        )}
      </div>
    </PortalAuthShell>
  );
}
