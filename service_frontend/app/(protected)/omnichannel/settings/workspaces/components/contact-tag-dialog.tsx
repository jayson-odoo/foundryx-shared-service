'use client';

/**
 * Create/edit dialog for a workspace tag (plan 25, AC-CDM-32). Colour reuses
 * the status-engine's swatch + native-picker control (same primitive, not a
 * forked one) so the visual language matches the lifecycle canvas.
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
import { STATUS_COLOR_SWATCHES } from '@/components/platform/status-badge';
import { ApiError } from '@/lib/api-client';
import { cn } from '@/lib/utils';
import type { ContactTag } from '@/types/omnichannel';
import {
  contactTagSchema,
  defaultContactTagFormValues,
  type ContactTagFormValues,
} from './contact-tag-schema';

export interface ContactTagDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** null = create. */
  tag: ContactTag | null;
  onCreate: (values: ContactTagFormValues) => Promise<unknown>;
  onUpdate: (id: string, values: ContactTagFormValues) => Promise<unknown>;
}

function toValues(tag: ContactTag | null): ContactTagFormValues {
  if (!tag) return defaultContactTagFormValues();
  return {
    name: tag.name,
    emoji: tag.emoji ?? '',
    color: tag.color ?? '#6B7280',
    description: tag.description ?? '',
  };
}

export function ContactTagDialog({ open, onOpenChange, tag, onCreate, onUpdate }: ContactTagDialogProps) {
  const editing = !!tag;
  const [submitting, setSubmitting] = useState(false);

  const form = useForm<ContactTagFormValues>({
    resolver: zodResolver(contactTagSchema),
    defaultValues: toValues(null),
  });

  useEffect(() => {
    if (open) form.reset(toValues(tag));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, tag]);

  const submit = form.handleSubmit(async (values) => {
    setSubmitting(true);
    try {
      if (editing) {
        await onUpdate(tag.id, values);
        toast.success('Tag updated.');
      } else {
        await onCreate(values);
        toast.success('Tag created.');
      }
      onOpenChange(false);
    } catch (error) {
      if (error instanceof ApiError && error.status === 422) {
        const fieldErrors = (error.detail as { fieldErrors?: Record<string, string> } | undefined)?.fieldErrors;
        if (fieldErrors) {
          for (const [name, message] of Object.entries(fieldErrors)) {
            form.setError(name as keyof ContactTagFormValues, { message });
          }
        } else {
          toast.error(error.message);
        }
      } else {
        toast.error(error instanceof Error ? error.message : 'Could not save the tag.');
      }
    } finally {
      setSubmitting(false);
    }
  });

  const color = form.watch('color');

  return (
    <Dialog open={open} onOpenChange={(v) => !submitting && onOpenChange(v)}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{editing ? 'Edit tag' : 'Create tag'}</DialogTitle>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-4">
          <div className="flex gap-3">
            <div className="flex w-20 flex-col gap-1.5">
              <Label htmlFor="tag-emoji">Emoji</Label>
              <Input
                id="tag-emoji"
                value={form.watch('emoji')}
                onChange={(e) => form.setValue('emoji', e.target.value, { shouldValidate: true })}
                placeholder="⭐"
                className="text-center text-lg"
              />
            </div>
            <div className="flex flex-1 flex-col gap-1.5">
              <Label htmlFor="tag-name">Name</Label>
              <Input
                id="tag-name"
                autoFocus
                value={form.watch('name')}
                onChange={(e) => form.setValue('name', e.target.value, { shouldValidate: true })}
              />
              {form.formState.errors.name && (
                <p className="text-xs text-destructive">{form.formState.errors.name.message}</p>
              )}
            </div>
          </div>

          <div className="flex flex-col gap-2">
            <Label>Colour</Label>
            <div className="flex flex-wrap items-center gap-2">
              {STATUS_COLOR_SWATCHES.map((swatch) => (
                <button
                  key={swatch.hex}
                  type="button"
                  title={swatch.label}
                  aria-label={`Colour ${swatch.label}`}
                  onClick={() => form.setValue('color', swatch.hex)}
                  className={cn(
                    'size-7 rounded-full border transition-shadow',
                    color.toLowerCase() === swatch.hex.toLowerCase()
                      ? 'border-primary ring-2 ring-primary/40'
                      : 'border-border hover:ring-2 hover:ring-muted-foreground/20',
                  )}
                  style={{ backgroundColor: swatch.hex }}
                />
              ))}
              <label className="relative flex h-7 cursor-pointer items-center gap-1.5 rounded-md border border-border px-2 hover:bg-accent">
                <span className="size-4 rounded-full border border-border" style={{ backgroundColor: color }} />
                <span className="font-mono text-xs text-muted-foreground uppercase">{color}</span>
                <input
                  type="color"
                  value={color}
                  onChange={(e) => form.setValue('color', e.target.value)}
                  aria-label="Custom colour"
                  className="absolute inset-0 size-full cursor-pointer opacity-0"
                />
              </label>
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="tag-description">Description</Label>
            <Textarea
              id="tag-description"
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
            {editing ? 'Save changes' : 'Create tag'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
