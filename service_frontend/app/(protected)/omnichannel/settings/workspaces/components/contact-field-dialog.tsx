'use client';

/**
 * Create/edit dialog for a workspace contact field (plan 25, AC-CDM-31). Field
 * ID auto-slugs from Name until the user edits it directly or the field is
 * saved (`key`/`type` are then immutable, D6) - editing an existing field
 * disables both. Options editor renders only for `type = list`.
 */
import { useEffect, useState } from 'react';
import { zodResolver } from '@hookform/resolvers/zod';
import { useForm } from 'react-hook-form';
import { Plus, Trash2 } from 'lucide-react';
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
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import { SearchSelect } from '@/components/platform/search-select';
import { ApiError } from '@/lib/api-client';
import type { ContactField, ContactFieldType } from '@/types/omnichannel';
import {
  CONTACT_FIELD_TYPE_OPTIONS,
  CONTACT_FIELD_VISIBILITY_OPTIONS,
  contactFieldSchema,
  defaultContactFieldFormValues,
  slugifyFieldKey,
  type ContactFieldFormValues,
} from './contact-field-schema';

export interface ContactFieldDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** null = create. */
  field: ContactField | null;
  onCreate: (values: ContactFieldFormValues) => Promise<unknown>;
  onUpdate: (id: string, values: ContactFieldFormValues) => Promise<unknown>;
}

function toValues(field: ContactField | null): ContactFieldFormValues {
  if (!field) return defaultContactFieldFormValues();
  return {
    label: field.label,
    key: field.key,
    description: field.description ?? '',
    type: field.type,
    options: field.options ?? [],
    visibility: field.visibility,
  };
}

// F9 (plan-25 round-3 codex triage): a 422 `fieldErrors` key must ALWAYS map
// onto something visible - the known form fields render their error inline;
// anything else (a truly unmapped/unexpected server key) falls back to the
// dialog-level banner below rather than being silently dropped.
const KNOWN_FIELD_KEYS = new Set<keyof ContactFieldFormValues>([
  'label',
  'key',
  'description',
  'type',
  'options',
  'visibility',
]);

export function ContactFieldDialog({ open, onOpenChange, field, onCreate, onUpdate }: ContactFieldDialogProps) {
  const editing = !!field;
  const [keyTouched, setKeyTouched] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [unmappedErrors, setUnmappedErrors] = useState<string[]>([]);

  const form = useForm<ContactFieldFormValues>({
    resolver: zodResolver(contactFieldSchema),
    defaultValues: toValues(null),
  });

  useEffect(() => {
    if (open) {
      form.reset(toValues(field));
      setKeyTouched(editing); // existing key is user-authored - never auto-overwrite
      setUnmappedErrors([]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, field]);

  const submit = form.handleSubmit(async (values) => {
    setSubmitting(true);
    setUnmappedErrors([]);
    try {
      if (editing) {
        await onUpdate(field.id, values);
        toast.success('Field updated.');
      } else {
        await onCreate(values);
        toast.success('Field created.');
      }
      onOpenChange(false);
    } catch (error) {
      if (error instanceof ApiError && error.status === 422) {
        const fieldErrors = (error.detail as { fieldErrors?: Record<string, string> } | undefined)?.fieldErrors;
        if (fieldErrors) {
          const unmapped: string[] = [];
          for (const [name, message] of Object.entries(fieldErrors)) {
            const target = (name.startsWith('customFields.') ? 'options' : name) as keyof ContactFieldFormValues;
            if (KNOWN_FIELD_KEYS.has(target)) {
              form.setError(target, { message });
            } else {
              unmapped.push(message);
            }
          }
          if (unmapped.length > 0) setUnmappedErrors(unmapped);
        } else {
          toast.error(error.message);
        }
      } else {
        toast.error(error instanceof Error ? error.message : 'Could not save the field.');
      }
    } finally {
      setSubmitting(false);
    }
  });

  const options = form.watch('options');
  const type = form.watch('type');

  return (
    <Dialog open={open} onOpenChange={(v) => !submitting && onOpenChange(v)}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{editing ? 'Edit field' : 'Add custom field'}</DialogTitle>
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
            <Label htmlFor="cf-label">Name</Label>
            <Input
              id="cf-label"
              autoFocus
              value={form.watch('label')}
              onChange={(e) => {
                const label = e.target.value;
                form.setValue('label', label, { shouldValidate: true });
                if (!keyTouched) {
                  form.setValue('key', slugifyFieldKey(label), { shouldValidate: true });
                }
              }}
            />
            {form.formState.errors.label && (
              <p className="text-xs text-destructive">{form.formState.errors.label.message}</p>
            )}
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="cf-key">Field ID</Label>
            <Input
              id="cf-key"
              value={form.watch('key')}
              disabled={editing}
              onChange={(e) => {
                setKeyTouched(true);
                form.setValue('key', e.target.value, { shouldValidate: true });
              }}
              className="font-mono text-sm"
            />
            {form.formState.errors.key && (
              <p className="text-xs text-destructive">{form.formState.errors.key.message}</p>
            )}
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="cf-description">Description</Label>
            <Textarea
              id="cf-description"
              rows={2}
              value={form.watch('description')}
              onChange={(e) => form.setValue('description', e.target.value)}
            />
            {form.formState.errors.description && (
              <p className="text-xs text-destructive">{form.formState.errors.description.message}</p>
            )}
          </div>

          <div className="flex flex-col gap-1.5">
            <Label>Type</Label>
            <SearchSelect
              options={CONTACT_FIELD_TYPE_OPTIONS.map((o) => ({ label: o.label, value: o.value }))}
              value={type}
              onChange={(v) => form.setValue('type', v as ContactFieldType, { shouldValidate: true })}
              disabled={editing}
              ariaLabel="Field type"
            />
            {form.formState.errors.type && (
              <p className="text-xs text-destructive">{form.formState.errors.type.message}</p>
            )}
          </div>

          {type === 'list' && (
            <div className="flex flex-col gap-1.5">
              <Label>Options</Label>
              <div className="flex flex-col gap-1.5" data-testid="contact-field-options">
                {options.map((opt, i) => (
                  <div key={i} className="flex items-center gap-1.5">
                    <Input
                      value={opt}
                      placeholder={`Option ${i + 1}`}
                      onChange={(e) => {
                        const next = [...options];
                        next[i] = e.target.value;
                        form.setValue('options', next, { shouldValidate: true });
                      }}
                      className="h-8 flex-1 text-sm"
                    />
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="size-7 text-destructive"
                      aria-label="Remove option"
                      onClick={() =>
                        form.setValue(
                          'options',
                          options.filter((_, idx) => idx !== i),
                          { shouldValidate: true },
                        )
                      }
                    >
                      <Trash2 className="size-3.5" />
                    </Button>
                  </div>
                ))}
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-7 self-start text-xs"
                  onClick={() => form.setValue('options', [...options, ''], { shouldValidate: true })}
                >
                  <Plus className="size-3.5" /> Add option
                </Button>
              </div>
              {form.formState.errors.options && (
                <p className="text-xs text-destructive">{form.formState.errors.options.message}</p>
              )}
            </div>
          )}

          <div className="flex flex-col gap-1.5">
            <Label>Visibility</Label>
            <SearchSelect
              options={CONTACT_FIELD_VISIBILITY_OPTIONS.map((o) => ({ label: o.label, value: o.value }))}
              value={form.watch('visibility')}
              onChange={(v) => form.setValue('visibility', v as ContactField['visibility'], { shouldValidate: true })}
              ariaLabel="Field visibility"
            />
            {form.formState.errors.visibility && (
              <p className="text-xs text-destructive">{form.formState.errors.visibility.message}</p>
            )}
          </div>
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={submitting}>
            Cancel
          </Button>
          <Button variant="primary" onClick={submit} disabled={submitting}>
            {editing ? 'Save changes' : 'Add field'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
