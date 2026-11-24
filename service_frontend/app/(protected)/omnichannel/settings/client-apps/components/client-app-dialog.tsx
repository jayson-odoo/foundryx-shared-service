'use client';

/** Create/rename dialog for a client app - a single name field. */
import { useEffect, useState } from 'react';
import { zodResolver } from '@hookform/resolvers/zod';
import { useForm } from 'react-hook-form';
import { toast } from '@/lib/toast';
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
import type { ClientApp } from '@/types/omnichannel';
import {
  clientAppSchema,
  defaultClientAppFormValues,
  type ClientAppFormValues,
} from './client-app-schema';

export interface ClientAppDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** null = create. */
  app: ClientApp | null;
  onCreate: (values: ClientAppFormValues) => Promise<unknown>;
  onRename: (id: string, values: ClientAppFormValues) => Promise<unknown>;
}

export function ClientAppDialog({ open, onOpenChange, app, onCreate, onRename }: ClientAppDialogProps) {
  const editing = !!app;
  const [submitting, setSubmitting] = useState(false);

  const form = useForm<ClientAppFormValues>({
    mode: 'onTouched',
    resolver: zodResolver(clientAppSchema),
    defaultValues: defaultClientAppFormValues(),
  });

  useEffect(() => {
    if (open) form.reset(defaultClientAppFormValues(app?.name ?? ''));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, app]);

  const submit = form.handleSubmit(async (values) => {
    setSubmitting(true);
    try {
      if (editing) {
        await onRename(app.id, values);
        toast.success('Client app renamed.');
      } else {
        await onCreate(values);
        toast.success('Client app created.');
      }
      onOpenChange(false);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not save the client app.');
    } finally {
      setSubmitting(false);
    }
  });

  return (
    <Dialog open={open} onOpenChange={(v) => !submitting && onOpenChange(v)}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>{editing ? 'Rename client app' : 'Create client app'}</DialogTitle>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="client-app-name">Name</Label>
            <Input
              id="client-app-name"
              autoFocus
              value={form.watch('name')}
              onChange={(e) => form.setValue('name', e.target.value, { shouldValidate: true })}
              data-testid="client-app-name"
            />
            {form.formState.errors.name && (
              <p className="text-xs text-destructive">{form.formState.errors.name.message}</p>
            )}
          </div>
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            Cancel
          </Button>
          <Button variant="primary" onClick={submit} disabled={submitting} data-testid="client-app-submit">
            {editing ? 'Save changes' : 'Create client app'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
