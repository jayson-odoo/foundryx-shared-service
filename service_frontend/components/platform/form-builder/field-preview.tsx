'use client';

/**
 * Compact, NON-interactive canvas approximation of a field (plan sprint-3/01
 * D6). Renders a disabled-looking control matching the type so the author sees
 * the shape; display fields render themselves (heading/paragraph/divider).
 * Pure presentation - no inputs are wired, the real renderer lives in the fill
 * surface (slice 2). No instructional copy.
 */
import { ChevronDown, Star } from 'lucide-react';
import { isDisplayField } from '@/lib/form-doc';
import type { FormField } from '@/types/forms';

function FakeInput({ placeholder }: { placeholder?: string }) {
  return (
    <div className="flex h-8 items-center rounded-md border border-input bg-muted/40 px-2.5 text-xs text-muted-foreground">
      {placeholder || ''}
    </div>
  );
}

function FakeSelect({ placeholder }: { placeholder?: string }) {
  return (
    <div className="flex h-8 items-center justify-between rounded-md border border-input bg-muted/40 px-2.5 text-xs text-muted-foreground">
      <span>{placeholder || ''}</span>
      <ChevronDown className="size-3.5 opacity-50" />
    </div>
  );
}

function FieldBody({ field }: { field: FormField }) {
  switch (field.type) {
    case 'textarea':
      return (
        <div className="h-16 rounded-md border border-input bg-muted/40 px-2.5 py-1.5 text-xs text-muted-foreground">
          {field.placeholder || ''}
        </div>
      );
    case 'select':
    case 'multiselect':
      return <FakeSelect placeholder={field.placeholder} />;
    case 'radio':
    case 'checkboxes':
      return (
        <div className="flex flex-col gap-1">
          {(field.options?.items ?? []).slice(0, 4).map((item) => (
            <div key={item.value} className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <span
                className={`size-3 border border-input bg-background ${
                  field.type === 'radio' ? 'rounded-full' : 'rounded-sm'
                }`}
              />
              {item.label}
            </div>
          ))}
        </div>
      );
    case 'yesno':
      return (
        <div className="flex gap-2">
          <span className="rounded-md border border-input px-2.5 py-1 text-xs text-muted-foreground">
            Yes
          </span>
          <span className="rounded-md border border-input px-2.5 py-1 text-xs text-muted-foreground">
            No
          </span>
        </div>
      );
    case 'rating':
      return (
        <div className="flex gap-0.5">
          {Array.from({ length: Math.min(field.rating?.max ?? 5, 10) }).map((_, i) => (
            <Star key={i} className="size-4 text-muted-foreground/50" />
          ))}
        </div>
      );
    case 'file':
    case 'signature':
      return (
        <div className="flex h-12 items-center justify-center rounded-md border border-dashed border-input bg-muted/30 text-xs text-muted-foreground">
          {field.type === 'signature' ? 'Signature' : 'Upload'}
        </div>
      );
    case 'address':
      return (
        <div className="grid grid-cols-2 gap-1.5">
          <FakeInput placeholder="Address line 1" />
          <FakeInput placeholder="City" />
          <FakeInput placeholder="State" />
          <FakeInput placeholder="Postcode" />
        </div>
      );
    case 'repeater':
      return (
        <div className="rounded-md border border-dashed border-input bg-muted/20 p-2">
          <div className="flex flex-wrap gap-1.5">
            {(field.repeater?.fields ?? []).map((sub) => (
              <span
                key={sub.id}
                className="rounded border border-input bg-background px-1.5 py-0.5 text-[10px] text-muted-foreground"
              >
                {sub.label || sub.key}
              </span>
            ))}
          </div>
        </div>
      );
    case 'computed':
      return (
        <div className="flex h-8 items-center rounded-md border border-input bg-muted/40 px-2.5 font-mono text-xs text-muted-foreground">
          {field.computed?.expression || '='}
        </div>
      );
    default:
      // text, email, phone, url, number, date, datetime
      return <FakeInput placeholder={field.placeholder} />;
  }
}

export function FieldPreview({ field }: { field: FormField }) {
  if (isDisplayField(field)) {
    if (field.type === 'divider') return <hr className="border-input" />;
    if (field.type === 'heading') {
      const level = field.heading?.level ?? 2;
      const size = level === 1 ? 'text-lg' : level === 2 ? 'text-base' : 'text-sm';
      return <p className={`font-heading font-semibold ${size}`}>{field.label}</p>;
    }
    // paragraph
    return <p className="text-sm text-muted-foreground">{field.label}</p>;
  }

  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs font-medium text-foreground">
        {field.label}
        {field.required && <span className="ms-0.5 text-destructive">*</span>}
      </span>
      <FieldBody field={field} />
      {field.helpText && <span className="text-[11px] text-muted-foreground">{field.helpText}</span>}
    </div>
  );
}
