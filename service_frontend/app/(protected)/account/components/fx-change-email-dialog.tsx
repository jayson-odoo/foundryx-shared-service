'use client';

/**
 * The change-email request with the Foundryx UIUX switch on (slice
 * W4-ACCOUNT). The ceremony is today's, step for step: the new address and
 * the current password go to the same request; on success the dialog says
 * where the approval link went; nothing changes until the current inbox
 * approves and the new one confirms. Only the words and the look change:
 * - the safe button keeps the email ("Keep my email"); the red one says
 *   what it sends;
 * - field errors sit under their field, the request's error under the red
 *   button, without moving anything;
 * - the password eye is the field's own (`FxSecretInput`).
 *
 * The password leaves the form the moment it is sent: it is cleared from the
 * form state before the request resolves, never kept, shown, logged or
 * stored.
 */
import { useState } from 'react';
import { zodResolver } from '@hookform/resolvers/zod';
import { LoaderCircleIcon, MailCheck } from 'lucide-react';
import { useForm } from 'react-hook-form';
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
import { Input } from '@/components/ui/input';
import { FxActionError } from '@/components/fx/actions/action-error';
import { useHideMainAction } from '@/components/fx/actions/page-actions-context';
import { FxField, FxSecretInput } from '@/components/fx/fields';
import { ChangeEmailSchemaType, getChangeEmailSchema } from '../forms/change-email-schema';
import type { ChangeEmailDialogProps } from './change-email-dialog';

const PILL = 'h-auto min-h-11 rounded-(--fx-r-pill) px-5';

export function FxChangeEmailDialog({
  open,
  onOpenChange,
  currentEmail,
  isProcessing,
  error,
  onRequest,
  clearError,
}: ChangeEmailDialogProps) {
  const [sentTo, setSentTo] = useState<string | null>(null);
  useHideMainAction(open);

  const form = useForm<ChangeEmailSchemaType>({
    mode: 'onTouched',
    resolver: zodResolver(getChangeEmailSchema()),
    defaultValues: { newEmail: '', password: '' },
  });
  const errors = form.formState.errors;

  function handleOpenChange(next: boolean) {
    if (!next) {
      form.reset();
      setSentTo(null);
      clearError();
    }
    onOpenChange(next);
  }

  async function onSubmit(values: ChangeEmailSchemaType) {
    // Out of the form state before the request goes, whatever it answers.
    form.setValue('password', '', { shouldValidate: false, shouldDirty: false });
    const ok = await onRequest(values.newEmail, values.password);
    if (ok) setSentTo(values.newEmail);
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-md">
        {sentTo ? (
          <>
            <DialogHeader>
              <DialogTitle>Approve it from {currentEmail || 'your current inbox'}</DialogTitle>
              <DialogDescription>
                Then confirm from {sentTo}. Your email stays {currentEmail || 'as it is'} until
                both are done.
              </DialogDescription>
            </DialogHeader>
            <DialogBody>
              <p className="flex items-center gap-2 text-sm text-(--fx-ink-2)">
                <MailCheck aria-hidden="true" className="size-4 shrink-0 text-(--fx-link)" />
                Each link works once and stops working after a short while.
              </p>
            </DialogBody>
            <DialogFooter>
              <Button variant="fx-main" className={PILL} onClick={() => handleOpenChange(false)}>
                Close
              </Button>
            </DialogFooter>
          </>
        ) : (
          // noValidate: zod owns validation, as with the switch off.
          <form onSubmit={form.handleSubmit(onSubmit)} noValidate>
            <DialogHeader>
              <DialogTitle>Change your email?</DialogTitle>
              <DialogDescription>
                Nothing changes until {currentEmail || 'your current inbox'} approves and the new
                address confirms.
              </DialogDescription>
            </DialogHeader>
            <DialogBody className="flex flex-col gap-7">
              <FxField
                label="New email"
                id="fx-change-email-new"
                tone="error"
                message={errors.newEmail?.message}
              >
                <Input
                  id="fx-change-email-new"
                  placeholder="you@example.com"
                  type="email"
                  autoComplete="email"
                  aria-invalid={errors.newEmail ? true : undefined}
                  {...form.register('newEmail')}
                />
              </FxField>
              <FxField
                label="Current password"
                id="fx-change-email-password"
                tone="error"
                message={errors.password?.message}
              >
                <FxSecretInput
                  id="fx-change-email-password"
                  autoComplete="current-password"
                  aria-invalid={errors.password ? true : undefined}
                  {...form.register('password')}
                />
              </FxField>
            </DialogBody>
            <DialogFooter className="gap-2">
              <Button
                type="button"
                variant="fx-quiet"
                className={PILL}
                onClick={() => handleOpenChange(false)}
              >
                Keep my email
              </Button>
              <span className="relative flex flex-col items-end">
                <Button type="submit" variant="fx-main" className={PILL} disabled={isProcessing}>
                  {isProcessing ? <LoaderCircleIcon className="size-4 animate-spin" /> : null}
                  Send approval link
                </Button>
                <FxActionError message={error} />
              </span>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
