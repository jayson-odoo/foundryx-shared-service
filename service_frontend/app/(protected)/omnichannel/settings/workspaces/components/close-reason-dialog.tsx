'use client';

/**
 * Create/edit dialog for a close reason (plan 27, AC-IVE-25). Clones
 * `contact-tag-dialog.tsx`'s shape (name + a couple of small fields).
 */
import { useEffect, useState } from 'react';
import { zodResolver } from '@hookform/resolvers/zod';
import { useForm } from 'react-hook-form';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { ApiError } from '@/lib/api-client';
import type { CloseReason } from '@/types/omnichannel';
import {
  closeReasonSchema,
  defaultCloseReasonFormValues,
  type CloseReasonFormValues,
} from './close-reason-schema';

export interface CloseReasonDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** null = create. */
  reason: CloseReason | null;
  /** Next sort order offered when creating. */
  nextSortOrder: number;
  onCreate: (values: CloseReasonFormValues) => Promise<unknown>;
  onUpdate: (id: string, values: CloseReasonFormValues) => Promise<unknown>;
}

function toValues(reason: CloseReason | null, nextSortOrder: number): CloseReasonFormValues {
  if (!reason) return defaultCloseReasonFormValues(nextSortOrder);
  return { name: reason.name, sortOrder: reason.sortOrder, isActive: reason.isActive };
}

const KNOWN_FIELD_KEYS = new Set<keyof CloseReasonFormValues>(['name', 'sortOrder', 'isActive']);

export function CloseReasonDialog({
  open,
  onOpenChange,
  reason,
  nextSortOrder,
  onCreate,
  onUpdate,
}: CloseReasonDialogProps) {
  const editing = !!reason;
  const [submitting, setSubmitting] = useState(false);
  const [unmappedErrors, setUnmappedErrors] = useState<string[]>([]);

  const form = useForm<CloseReasonFormValues>({
    resolver: zodResolver(closeReasonSchema),
    defaultValues: toValues(null, nextSortOrder),
  });

  useEffect(() => {
    if (open) {
      form.reset(toValues(reason, nextSortOrder));
      setUnmappedErrors([]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, reason]);

  const submit = form.handleSubmit(async (values) => {
    setSubmitting(true);
    setUnmappedErrors([]);
    try {
      if (editing) {
        await onUpdate(reason.id, values);
        toast.success('Close reason updated.');
      } else {
        await onCreate(values);
        toast.success('Close reason created.');
      }
      onOpenChange(false);
    } catch (error) {
      if (error instanceof ApiError && error.status === 422) {
        const fieldErrors = (error.detail as { fieldErrors?: Record<string, string> } | undefined)?.fieldErrors;
        if (fieldErrors) {
          const unmapped: string[] = [];
          for (const [name, message] of Object.entries(fieldErrors)) {
            const target = name as keyof CloseReasonFormValues;
            if (KNOWN_FIELD_KEYS.has(target)) form.setError(target, { message });
            else unmapped.push(message);
          }
          if (unmapped.length > 0) setUnmappedErrors(unmapped);
        } else {
          toast.error(error.message);
        }
      } else {
        toast.error(error instanceof Error ? error.message : 'Could not save the close reason.');
      }
    } finally {
      setSubmitting(false);
    }
  });

  return (
    <Dialog open={open} onOpenChange={(v) => !submitting && onOpenChange(v)}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>{editing ? 'Edit close reason' : 'Create close reason'}</DialogTitle>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-4">
          {unmappedErrors.length > 0 && (
            <div className="rounded-md border border-destructive/30 bg-destructive/5 p-2 text-xs text-destructive">
              {unmappedErrors.map((message, i) => (
                <p key={i}>{message}</p>
              ))}
            </div>
          )}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="reason-name">Name</Label>
            <Input
              id="reason-name"
              autoFocus
              value={form.watch('name')}
              onChange={(e) => form.setValue('name', e.target.value, { shouldValidate: true })}
              data-testid="close-reason-name"
            />
            {form.formState.errors.name && (
              <p className="text-xs text-destructive">{form.formState.errors.name.message}</p>
            )}
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="reason-sort">Sort order</Label>
            <Input
              id="reason-sort"
              type="number"
              min={0}
              value={form.watch('sortOrder')}
              onChange={(e) => form.setValue('sortOrder', Number(e.target.value) || 0)}
            />
          </div>
          <div className="flex items-center justify-between gap-3 rounded-md border p-3">
            <Label htmlFor="reason-active" className="cursor-pointer">
              Active
            </Label>
            <Switch
              id="reason-active"
              checked={form.watch('isActive')}
              onCheckedChange={(v) => form.setValue('isActive', v)}
            />
          </div>
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            Cancel
          </Button>
          <Button variant="primary" onClick={submit} disabled={submitting} data-testid="close-reason-submit">
            {editing ? 'Save changes' : 'Create close reason'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
