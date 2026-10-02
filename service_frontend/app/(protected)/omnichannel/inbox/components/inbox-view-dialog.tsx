'use client';

/**
 * Save/rename saved-view dialog (plan 27, AC-IVE-18/22). Create captures the
 * CURRENT filter snapshot; edit only touches name/shared (the filter itself
 * isn't re-editable here - re-save-as-new covers that). The Shared switch is
 * HIDDEN (not just disabled) for a caller without `inbox_views.manage`
 * (D-A3-11) - foolproof-UI, never offer a control that will 403.
 */
import { useEffect, useState } from 'react';
import { zodResolver } from '@hookform/resolvers/zod';
import { useForm } from 'react-hook-form';
import { toast } from '@/lib/toast';
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
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { ApiError } from '@/lib/api-client';
import type { InboxView } from '@/types/omnichannel';
import {
  defaultInboxViewFormValues,
  inboxViewSchema,
  type InboxViewFormValues,
} from './inbox-view-schema';

export interface InboxViewDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** null = create (a new saved view over the current filters). */
  view: InboxView | null;
  /** Hides the Shared switch entirely when false (foolproof-UI, D-A3-11). */
  canShare: boolean;
  onCreate: (values: InboxViewFormValues) => Promise<unknown>;
  onUpdate: (id: string, values: InboxViewFormValues) => Promise<unknown>;
}

function toValues(view: InboxView | null): InboxViewFormValues {
  if (!view) return defaultInboxViewFormValues();
  return { name: view.name, isShared: view.isShared };
}

export function InboxViewDialog({ open, onOpenChange, view, canShare, onCreate, onUpdate }: InboxViewDialogProps) {
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
        const fieldErrors = (error.detail as { fieldErrors?: Record<string, string> } | undefined)?.fieldErrors;
        if (fieldErrors?.name) form.setError('name', { message: fieldErrors.name });
        else toast.error(error.message);
      } else {
        toast.error(error instanceof Error ? error.message : 'Could not save the view.');
      }
    } finally {
      setSubmitting(false);
    }
  });

  return (
    <Dialog open={open} onOpenChange={(v) => !submitting && onOpenChange(v)}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>{editing ? 'Rename view' : 'Save view'}</DialogTitle>
          <DialogDescription>
            {editing ? 'A saved view\'s name and sharing.' : 'A saved snapshot of the current filters.'}
          </DialogDescription>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="view-name">Name</Label>
            <Input
              id="view-name"
              autoFocus
              value={form.watch('name')}
              onChange={(e) => form.setValue('name', e.target.value, { shouldValidate: true })}
              data-testid="inbox-view-name"
            />
            {form.formState.errors.name && (
              <p className="text-xs text-destructive">{form.formState.errors.name.message}</p>
            )}
          </div>
          {canShare && (
            <div className="flex items-center justify-between gap-3 rounded-md border p-3">
              <Label htmlFor="view-shared" className="cursor-pointer">
                Shared with the workspace
              </Label>
              <Switch
                id="view-shared"
                checked={form.watch('isShared')}
                onCheckedChange={(v) => form.setValue('isShared', v)}
                data-testid="inbox-view-shared"
              />
            </div>
          )}
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={submit}
            disabled={submitting || !form.watch('name').trim()}
            data-testid="inbox-view-submit"
          >
            {editing ? 'Save changes' : 'Save view'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
