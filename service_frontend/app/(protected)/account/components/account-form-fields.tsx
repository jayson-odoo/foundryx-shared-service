'use client';

import type { UseFormReturn } from 'react-hook-form';
import { Info, LoaderCircleIcon } from 'lucide-react';
import { toast } from '@/lib/toast';
import { Alert, AlertIcon, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import {
  FormControl,
  FormField,
  FormItem,
  FormMessage,
} from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { FormRow } from '@/components/platform/resource-form';
import type { UseEmailChangeResult } from '@/hooks/use-email-change';
import type { AccountFormValues } from './use-account-form';

export interface AccountProfileTabProps {
  form: UseFormReturn<AccountFormValues>;
  editing: boolean;
  name: string | null;
  email: string;
  roles: { id: string; name: string }[];
  emailChange: UseEmailChangeResult;
}

/**
 * Profile tab - name is the one self-editable field. Email is click-to-copy;
 * changing it = the "…" → Change email action (plan-04 ceremony), explained
 * by the info tooltip. An outstanding ceremony shows as the banner up top.
 */
export function AccountProfileTab({
  form,
  editing,
  name,
  email,
  roles,
  emailChange,
}: AccountProfileTabProps) {
  const pending = emailChange.pending;

  const copyEmail = async () => {
    try {
      await navigator.clipboard.writeText(email);
      toast.success('Email copied to clipboard.');
    } catch {
      toast.error('Could not copy.');
    }
  };

  return (
    <div className="flex flex-col gap-5">
      {pending && (
        <Alert>
          <AlertIcon>
            <LoaderCircleIcon className="animate-spin" />
          </AlertIcon>
          <AlertTitle className="flex grow flex-wrap items-center justify-between gap-2">
            <span>
              {pending.status === 'PENDING_OLD'
                ? `Change to ${pending.newEmail} awaits approval from your current inbox.`
                : `Change to ${pending.newEmail} awaits confirmation from the new inbox.`}
            </span>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => emailChange.cancelChange()}
              disabled={emailChange.isProcessing}
            >
              Cancel request
            </Button>
          </AlertTitle>
        </Alert>
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

          <FormRow label="Email address">
            <div className="flex items-center gap-1.5">
              <Tooltip>
                <TooltipTrigger asChild>
                  <button
                    type="button"
                    className="cursor-pointer hover:text-primary"
                    onClick={() => void copyEmail()}
                  >
                    {email || '-'}
                  </button>
                </TooltipTrigger>
                <TooltipContent side="bottom">Click to copy</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger asChild>
                  <span tabIndex={0} aria-label="How to change your email">
                    <Info className="size-3.5 text-muted-foreground" />
                  </span>
                </TooltipTrigger>
                <TooltipContent side="bottom" className="max-w-xs">
                  To change your email address, use “…” → Change email. It
                  needs approval from your current inbox, then confirmation
                  from the new one.
                </TooltipContent>
              </Tooltip>
            </div>
          </FormRow>

          <FormRow label="Roles">
            <div className="flex flex-wrap gap-1.5">
              {roles.map((role) => (
                <Badge key={role.id} variant="secondary" size="sm">
                  {role.name}
                </Badge>
              ))}
              {roles.length === 0 && <span className="text-muted-foreground">-</span>}
            </div>
          </FormRow>
        </CardContent>
      </Card>
    </div>
  );
}
