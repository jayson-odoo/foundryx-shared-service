'use client';

/**
 * The save/rename saved-view form (plan 27, AC-IVE-18/22), shared by both
 * looks of `inbox-view-dialog.tsx`: create captures the current filters,
 * edit touches only the name and sharing.
 */
import { useEffect, useState } from 'react';
import { zodResolver } from '@hookform/resolvers/zod';
import { useForm } from 'react-hook-form';
import type { InboxView } from '@/types/omnichannel';
import { ApiError } from '@/lib/api-client';
import { toast } from '@/lib/toast';
import {
  defaultInboxViewFormValues,
  inboxViewSchema,
  type InboxViewFormValues,
} from './inbox-view-schema';

function toValues(view: InboxView | null): InboxViewFormValues {
  if (!view) return defaultInboxViewFormValues();
  return { name: view.name, isShared: view.isShared };
}

export interface UseInboxViewFormArgs {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  view: InboxView | null;
  onCreate: (values: InboxViewFormValues) => Promise<unknown>;
  onUpdate: (id: string, values: InboxViewFormValues) => Promise<unknown>;
}

export function useInboxViewForm({
  open,
  onOpenChange,
  view,
  onCreate,
  onUpdate,
}: UseInboxViewFormArgs) {
  const editing = !!view;
  const [submitting, setSubmitting] = useState(false);

  const form = useForm<InboxViewFormValues>({
    mode: 'onTouched',
    resolver: zodResolver(inboxViewSchema),
    defaultValues: toValues(null),
  });

  useEffect(() => {
    if (open) form.reset(toValues(view));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, view]);

  const submit = form.handleSubmit(async (values) => {
    setSubmitting(true);
    try {
      if (editing) {
        await onUpdate(view.id, values);
        toast.success('View updated.');
      } else {
        await onCreate(values);
        toast.success('View saved.');
      }
      onOpenChange(false);
    } catch (error) {
      if (error instanceof ApiError && error.status === 422) {
        const fieldErrors = (
          error.detail as { fieldErrors?: Record<string, string> } | undefined
        )?.fieldErrors;
        if (fieldErrors?.name)
          form.setError('name', { message: fieldErrors.name });
        else toast.error(error.message);
      } else {
        toast.error(
          error instanceof Error ? error.message : 'Could not save the view.',
        );
      }
    } finally {
      setSubmitting(false);
    }
  });

  return { editing, submitting, form, submit };
}
