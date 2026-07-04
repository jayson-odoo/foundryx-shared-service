'use client';

import { useState } from 'react';
import Link from 'next/link';
import { zodResolver } from '@hookform/resolvers/zod';
import { AlertCircle, Eye, EyeOff, LoaderCircleIcon } from 'lucide-react';
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
import { useSignin } from '@/hooks/use-signin';
import { useTenantBranding } from '@/hooks/use-branding';
import { signupEnabled } from '@/lib/auth-flags';
import { getSigninSchema, SigninSchemaType } from '../forms/signin-schema';

export default function Page() {
  const [passwordVisible, setPasswordVisible] = useState(false);
  const { signin, isProcessing, error } = useSignin('/');
  // White-label: the tenant's chosen system name, then its org name; never the
  // FoundryX product name. Unresolved/unbranded → a neutral greeting.
  const { branding } = useTenantBranding();
  const welcomeName = branding.appName || branding.tenantName;

  const form = useForm<SigninSchemaType>({
    resolver: zodResolver(getSigninSchema()),
    defaultValues: {
      email: '',
      password: '',
      rememberMe: false,
    },
  });

  async function onSubmit(values: SigninSchemaType) {
    await signin(values);
  }

  return (
    <Form {...form}>
      <form
        onSubmit={form.handleSubmit(onSubmit)}
        className="block w-full space-y-6"
      >
        <div className="space-y-2">
          <h1 className="font-heading text-3xl font-semibold tracking-tight text-mono">
            {welcomeName ? `Welcome to ${welcomeName}.` : 'Welcome back.'}
          </h1>
          {signupEnabled && (
            <p className="font-heading text-base font-medium text-muted-foreground">
              New Here?{' '}
              <Link
                href="/signup"
                className="font-semibold text-primary hover:text-primary-active"
              >
                Create an Account
              </Link>
            </p>
          )}
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
              <FormLabel className="font-heading font-semibold">Email</FormLabel>
              <FormControl>
                <Input placeholder="Your email" {...field} />
              </FormControl>
              <FormMessage />
            </FormItem>
          )}
        />

        <FormField
          control={form.control}
          name="password"
          render={({ field }) => (
            <FormItem>
              <div className="flex items-center justify-between gap-2.5">
                <FormLabel className="font-heading font-semibold">
                  Password
                </FormLabel>
                <Link
                  href="/reset-password"
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
          name="rememberMe"
          render={({ field }) => (
            <FormItem className="flex flex-row items-center gap-2.5 space-y-0">
              <FormControl>
                <Checkbox
                  checked={field.value ?? false}
                  onCheckedChange={(checked) => field.onChange(checked === true)}
                  aria-label="Remember me"
                />
              </FormControl>
              <FormLabel className="font-heading text-sm font-medium text-muted-foreground">
                Remember me
              </FormLabel>
            </FormItem>
          )}
        />

        <Button type="submit" className="w-full" disabled={isProcessing}>
          {isProcessing ? (
            <LoaderCircleIcon className="size-4 animate-spin" />
          ) : null}
          Sign In
        </Button>
      </form>
    </Form>
  );
}
