'use client';

/**
 * "Save as segment" dialog (AC-CTM-06) - names the CURRENT ad-hoc filter tree
 * and stores it as a workspace segment. Only ever opened with a non-empty
 * filter (the page gates the trigger button on that) - a name-only, no-filter
 * segment would be indistinguishable from "All contacts" (foolproof-UI).
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
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { ApiError } from '@/lib/api-client';
import type { FilterGroup } from '@/types/resource';
import { defaultSegmentFormValues, segmentFormSchema, type SegmentFormValues } from './segment-schema';

export interface SaveSegmentDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  filter: FilterGroup;
  onSave: (values: SegmentFormValues) => Promise<unknown>;
}

export function SaveSegmentDialog({ open, onOpenChange, filter, onSave }: SaveSegmentDialogProps) {
  void filter; // the tree itself is carried by the caller; this dialog only names it
  const [submitting, setSubmitting] = useState(false);
  const form = useForm<SegmentFormValues>({
    resolver: zodResolver(segmentFormSchema),
    defaultValues: defaultSegmentFormValues(),
  });

  useEffect(() => {
    if (open) form.reset(defaultSegmentFormValues());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const submit = form.handleSubmit(async (values) => {
    setSubmitting(true);
    try {
      await onSave(values);
      toast.success('Segment saved.');
      onOpenChange(false);
    } catch (error) {
      if (error instanceof ApiError && error.status === 422) {
        const fieldErrors = (error.detail as { fieldErrors?: Record<string, string> } | undefined)?.fieldErrors;
        if (fieldErrors?.name) form.setError('name', { message: fieldErrors.name });
        else toast.error(error.message);
      } else {
        toast.error(error instanceof Error ? error.message : 'Could not save the segment.');
      }
    } finally {
      setSubmitting(false);
    }
  });

  return (
    <Dialog open={open} onOpenChange={(v) => !submitting && onOpenChange(v)}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Save as segment</DialogTitle>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="segment-name">Name</Label>
            <Input
              id="segment-name"
              autoFocus
              value={form.watch('name')}
              onChange={(e) => form.setValue('name', e.target.value, { shouldValidate: true })}
            />
            {form.formState.errors.name && (
              <p className="text-xs text-destructive">{form.formState.errors.name.message}</p>
            )}
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="segment-description">Description</Label>
            <Textarea
              id="segment-description"
              rows={2}
              value={form.watch('description')}
              onChange={(e) => form.setValue('description', e.target.value)}
            />
          </div>
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            Cancel
          </Button>
          <Button variant="primary" onClick={submit} disabled={submitting}>
            Save segment
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
