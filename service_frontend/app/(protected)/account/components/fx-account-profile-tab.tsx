'use client';

/**
 * My Account's Profile tab with the Foundryx UIUX switch on (slice
 * W4-ACCOUNT). The same fields and the same requests as with the switch off;
 * what changes is how it reads:
 * - name and email are plain values with Hold to Copy (the shared form row
 *   does that); the "how to change your email" tip goes, since Change email
 *   is now an icon action in the page header;
 * - an email change still waiting shows which inbox it waits on, with
 *   "Cancel email change" beside it and a done toast once it is cancelled
 *   (no Undo: starting a change again needs the password).
 */
import { useEffect, useRef } from 'react';
import { MailCheck } from 'lucide-react';
import { toast } from '@/lib/toast';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { FormControl, FormField, FormItem, FormMessage } from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { FormRow } from '@/components/platform/resource-form';
import { FxActionError } from '@/components/fx/actions/action-error';
import type { PendingEmailChange } from '@/types/account';
import type { AccountProfileTabProps } from './account-form-fields';

/** The words of a waiting email change (pure, tested). */
export function fxPendingWords(pending: PendingEmailChange, currentEmail: string): string {
  return pending.status === 'PENDING_OLD'
    ? `Your email changes to ${pending.newEmail} once ${currentEmail || 'your current inbox'} approves it.`
    : `Your email changes to ${pending.newEmail} once that inbox confirms it.`;
}

export function FxAccountProfileTab({
  form,
  editing,
  name,
  email,
  roles,
  emailChange,
}: AccountProfileTabProps) {
  const pending = emailChange.pending;

  // Cancel resolves without saying whether it worked (the hook keeps the
  // error); the toast follows the waiting change actually going away.
  const cancelling = useRef<string | null>(null);
  useEffect(() => {
    if (!cancelling.current) return;
    if (!pending) {
      toast.fxDone({ what: 'Email change cancelled', forWhom: cancelling.current });
      cancelling.current = null;
    } else if (emailChange.error) {
      cancelling.current = null;
    }
  }, [pending, emailChange.error]);

  const cancel = () => {
    if (!pending) return;
    cancelling.current = pending.newEmail;
    void emailChange.cancelChange();
  };

  return (
    <div className="flex flex-col gap-5">
      {pending && (
        <div
          data-fx-email-pending=""
          className="flex flex-wrap items-center justify-between gap-3 rounded-(--fx-r-l) border border-(--fx-line) bg-(--fx-info-bg) px-4 py-3 text-sm text-(--fx-ink)"
        >
          <span className="flex min-w-0 items-center gap-2">
            <MailCheck aria-hidden="true" className="size-4 shrink-0 text-(--fx-link)" />
            <span className="min-w-0 break-words">{fxPendingWords(pending, email)}</span>
          </span>
          <span className="relative">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={cancel}
              disabled={emailChange.isProcessing}
            >
              Cancel email change
            </Button>
            <FxActionError message={emailChange.error && !editing ? emailChange.error : null} />
          </span>
        </div>
      )}

      <Card>
        <CardContent className="py-1">
          <FormRow label="Full name" required={editing}>
            {editing ? (
              <FormField
                control={form.control}
                name="name"
                render={({ field }) => (
                  <FormItem className="max-w-sm">
                    <FormControl>
                      <Input placeholder="Full name" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            ) : (
              (name ?? '-')
            )}
          </FormRow>

          <FormRow label="Email address">{email || '-'}</FormRow>

          <FormRow label="Roles">
            <div className="flex flex-wrap gap-1.5">
              {roles.map((role) => (
                <Badge key={role.id} variant="secondary" size="sm">
                  {role.name}
                </Badge>
              ))}
              {roles.length === 0 && <span className="text-(--fx-ink-3)">-</span>}
            </div>
          </FormRow>
        </CardContent>
      </Card>
    </div>
  );
}
