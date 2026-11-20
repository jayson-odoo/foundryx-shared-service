'use client';

/**
 * Create-contact form fields (D-A2-4, AC-CTM-08) - First name, Last name,
 * Phone (required, create-only), Email, Language, Country, Lifecycle stage
 * (defaulted to the workspace's initial stage - foolproof-UI, only real
 * workspace stages are offered), Tags and one typed input per registered
 * custom field (same input renderer family as `contact-details-form.tsx`'s
 * `CustomFieldInput`, so a field "looks" the same everywhere it's edited).
 */
import type { UseFormReturn } from 'react-hook-form';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { SearchSelect } from '@/components/platform/search-select';
import { MultiSelect } from '@/components/platform/multi-select';
import type { LifecycleStageOption } from '@/hooks/use-contact-lifecycle-stages';
import type { ContactField, ContactTag } from '@/types/omnichannel';
import type { ContactCreateValues } from './contact-schema';

type CustomFieldValue = string | number | boolean | null;

export interface ContactFormFieldsProps {
  form: UseFormReturn<ContactCreateValues>;
  stages: LifecycleStageOption[];
  tags: ContactTag[];
  fields: ContactField[];
  customValues: Record<string, CustomFieldValue>;
  onCustomChange: (key: string, value: CustomFieldValue) => void;
  customErrors: Record<string, string>;
}

export function ContactFormFields({
  form,
  stages,
  tags,
  fields,
  customValues,
  onCustomChange,
  customErrors,
}: ContactFormFieldsProps) {
  const errors = form.formState.errors;

  return (
    <div className="grid grid-cols-1 gap-x-4 gap-y-4 sm:grid-cols-2">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="c-first-name">First name</Label>
        <Input id="c-first-name" {...form.register('firstName')} />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="c-last-name">Last name</Label>
        <Input id="c-last-name" {...form.register('lastName')} />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="c-phone">Phone *</Label>
        <Input id="c-phone" {...form.register('phone')} />
        {errors.phone && <p className="text-xs text-destructive">{errors.phone.message}</p>}
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="c-email">Email</Label>
        <Input id="c-email" type="email" {...form.register('email')} />
        {errors.email && <p className="text-xs text-destructive">{errors.email.message}</p>}
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor="c-language">Language</Label>
        <Input id="c-language" placeholder="en" {...form.register('language')} />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="c-country">Country</Label>
        <Input id="c-country" placeholder="MY" maxLength={2} className="uppercase" {...form.register('countryCode')} />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label>Lifecycle stage</Label>
        <SearchSelect
          ariaLabel="Lifecycle stage"
          value={form.watch('lifecycleStatusId')}
          onChange={(v) => form.setValue('lifecycleStatusId', v)}
          options={stages.map((s) => ({ label: s.label, value: s.id }))}
        />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label>Tags</Label>
        <MultiSelect
          options={tags.map((t) => ({ label: `${t.emoji ? `${t.emoji} ` : ''}${t.name}`, value: t.id }))}
          value={form.watch('tagIds')}
          onChange={(v) => form.setValue('tagIds', v)}
          placeholder="Select tags…"
        />
      </div>

      {fields
        .filter((f) => f.visibility === 'always')
        .map((f) => (
          <div key={f.id} className="flex flex-col gap-1.5">
            <Label htmlFor={`c-cf-${f.id}`}>{f.label}</Label>
            <CustomFieldInput
              field={f}
              value={customValues[f.key] ?? null}
              onChange={(v) => onCustomChange(f.key, v)}
            />
            {customErrors[f.key] && <p className="text-xs text-destructive">{customErrors[f.key]}</p>}
          </div>
        ))}
    </div>
  );
}

function CustomFieldInput({
  field,
  value,
  onChange,
}: {
  field: ContactField;
  value: CustomFieldValue;
  onChange: (value: CustomFieldValue) => void;
}) {
  const id = `c-cf-${field.id}`;
  switch (field.type) {
    case 'list':
      return (
        <SearchSelect
          options={(field.options ?? []).map((o) => ({ label: o, value: o }))}
          value={typeof value === 'string' ? value : null}
          onChange={onChange}
          ariaLabel={field.label}
        />
      );
    case 'checkbox':
      return (
        <div className="flex h-9 items-center">
          <Checkbox id={id} checked={!!value} onCheckedChange={(v) => onChange(v === true)} />
        </div>
      );
    case 'number':
      return (
        <Input
          id={id}
          type="number"
          value={value === null || value === undefined ? '' : String(value)}
          onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))}
        />
      );
    case 'date':
      return (
        <Input
          id={id}
          type="date"
          value={typeof value === 'string' ? value : ''}
          onChange={(e) => onChange(e.target.value || null)}
        />
      );
    case 'time':
      return (
        <Input
          id={id}
          type="time"
          value={typeof value === 'string' ? value : ''}
          onChange={(e) => onChange(e.target.value || null)}
        />
      );
    case 'url':
      return (
        <Input
          id={id}
          type="url"
          value={typeof value === 'string' ? value : ''}
          onChange={(e) => onChange(e.target.value || null)}
        />
      );
    case 'email':
      return (
        <Input
          id={id}
          type="email"
          value={typeof value === 'string' ? value : ''}
          onChange={(e) => onChange(e.target.value || null)}
        />
      );
    default:
      return (
        <Input
          id={id}
          value={typeof value === 'string' ? value : ''}
          onChange={(e) => onChange(e.target.value || null)}
        />
      );
  }
}
