'use client';

import { useState } from 'react';
import { zodResolver } from '@hookform/resolvers/zod';
import { AlertCircle, Eye, EyeOff, LoaderCircleIcon, MailCheck } from 'lucide-react';
import { useForm } from 'react-hook-form';
import { Alert, AlertIcon, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import {
  ChangeEmailSchemaType,
  getChangeEmailSchema,
} from '../forms/change-email-schema';

export interface ChangeEmailDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The address the approve link goes to (the CURRENT mailbox). */
  currentEmail: string;
  isProcessing: boolean;
  error: string | null;
  /** Resolves true on success - the dialog flips to its "check your inbox" state. */
  onRequest: (newEmail: string, password: string) => Promise<boolean>;
  clearError: () => void;
}

/**
 * Change-email request dialog (plan sprint-2/04 §Frontend). New email +
 * current-password re-entry (fresh proof, not just a live session) → on
 * success shows the "check your current inbox" state; the page underneath
 * picks up the pending banner.
 */
export function ChangeEmailDialog({
  open,
  onOpenChange,
  currentEmail,
  isProcessing,
  error,
  onRequest,
  clearError,
}: ChangeEmailDialogProps) {
  const [passwordVisible, setPasswordVisible] = useState(false);
  const [sent, setSent] = useState(false);

  const form = useForm<ChangeEmailSchemaType>({
    mode: 'onTouched',
    resolver: zodResolver(getChangeEmailSchema()),
    defaultValues: { newEmail: '', password: '' },
  });

  function handleOpenChange(next: boolean) {
    if (!next) {
      form.reset();
      setSent(false);
      setPasswordVisible(false);
      clearError();
    }
    onOpenChange(next);
  }

  async function onSubmit(values: ChangeEmailSchemaType) {
    const ok = await onRequest(values.newEmail, values.password);
    if (ok) setSent(true);
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-md">
        {sent ? (
          <>
            <DialogHeader>
              <DialogTitle>Check your current inbox</DialogTitle>
              <DialogDescription>
                We sent an approval link to <strong>{currentEmail}</strong>.
                Approve the change there, then confirm from your new address.
                Nothing changes until both steps are done.
              </DialogDescription>
            </DialogHeader>
            <DialogBody>
              <Alert>
                <AlertIcon>
                  <MailCheck />
                </AlertIcon>
                <AlertTitle>
                  The link is single-use and expires after a short while.
                </AlertTitle>
              </Alert>
            </DialogBody>
            <DialogFooter>
              <Button onClick={() => handleOpenChange(false)}>Got it</Button>
            </DialogFooter>
          </>
        ) : (
          <Form {...form}>
            {/* noValidate: zod owns validation - native email validation would
                block submit (and differ from the schema's messages). */}
            <form onSubmit={form.handleSubmit(onSubmit)} noValidate>
              <DialogHeader>
                <DialogTitle>Change email</DialogTitle>
                <DialogDescription>
                  An approval link goes to your current address first; the new
                  address then confirms it can receive mail.
                </DialogDescription>
              </DialogHeader>
              <DialogBody className="space-y-4">
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
                  name="newEmail"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>New email</FormLabel>
                      <FormControl>
                        <Input
                          placeholder="you@example.com"
                          type="email"
                          autoComplete="email"
                          {...field}
                        />
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
                      <FormLabel>Current password</FormLabel>
                      <div className="relative">
                        <FormControl>
                          <Input
                            placeholder="Your current password"
                            type={passwordVisible ? 'text' : 'password'}
                            autoComplete="current-password"
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
              </DialogBody>
              <DialogFooter>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => handleOpenChange(false)}
                >
                  Cancel
                </Button>
                <Button type="submit" disabled={isProcessing}>
                  {isProcessing ? (
                    <LoaderCircleIcon className="size-4 animate-spin" />
                  ) : null}
                  Send approval link
                </Button>
              </DialogFooter>
            </form>
          </Form>
        )}
      </DialogContent>
    </Dialog>
  );
}
