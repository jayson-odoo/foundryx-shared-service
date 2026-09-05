'use client';

/**
 * Template-variable binding editor (plan 29, AC-BRD-07) - renders EXACTLY the
 * slots the chosen template declares (header text vars, body vars, dynamic
 * URL-button vars), each with a per-slot source `SearchSelect` (Static text |
 * Contact field); a Contact field binding requires a non-empty fallback. The
 * EXISTING `WaBubblePreview` (channel Templates builder) renders the filled
 * message against a sample contact - reused, never re-implemented.
 */
import { useEffect, useState } from 'react';
import { Input } from '@/components/ui/input';
import { SearchSelect } from '@/components/platform/search-select';
import { ClampedText } from '@/components/platform/clamped-text';
import { whatsappTemplateService } from '@/services/whatsapp-template-service';
import { WaBubblePreview } from '@/app/(protected)/omnichannel/settings/channels/[id]/templates/components/wa-bubble-preview';
import { CONTACT_FIELD_BINDING_OPTIONS } from '@/types/omnichannel';
import type { TemplateBinding, WhatsAppTemplate } from '@/types/omnichannel';
import type { WaTemplateDoc } from '@/types/whatsapp-template';

const SOURCE_OPTIONS = [
  { label: 'Static text', value: 'static' },
  { label: 'Contact field', value: 'contactField' },
];

/** Sample contact used for the live preview only (never sent). */
const SAMPLE_CONTACT: Record<string, string> = {
  firstName: 'Alex',
  lastName: 'Tan',
  phone: '+15551234567',
  email: 'alex.tan@example.com',
  language: 'English',
  countryCode: 'US',
  lifecycle: 'Lead',
};

function previewText(binding: TemplateBinding | undefined): string {
  if (!binding) return '';
  if (binding.source === 'static') return binding.text || '';
  const sample = SAMPLE_CONTACT[binding.field];
  return sample && sample.trim() ? sample : binding.fallback;
}

function BindingRow({
  label,
  binding,
  editing,
  onChange,
  testidPrefix,
}: {
  label: string;
  binding: TemplateBinding;
  editing: boolean;
  onChange: (next: TemplateBinding) => void;
  testidPrefix: string;
}) {
  return (
    <div className="grid gap-2 rounded-md border border-border p-3 sm:grid-cols-[140px_1fr]">
      <span className="text-sm font-medium text-foreground">{label}</span>
      <div className="flex flex-col gap-2">
        <SearchSelect
          options={SOURCE_OPTIONS}
          value={binding.source}
          onChange={(source) => {
            if (source === 'static') onChange({ source: 'static', text: '' });
            else onChange({ source: 'contactField', field: 'firstName', fallback: '' });
          }}
          disabled={!editing}
          ariaLabel={`${label} source`}
        />
        {binding.source === 'static' ? (
          <Input
            value={binding.text}
            onChange={(e) => onChange({ source: 'static', text: e.target.value })}
            disabled={!editing}
            data-testid={`${testidPrefix}-text`}
          />
        ) : (
          <div className="grid gap-2 sm:grid-cols-2">
            <SearchSelect
              options={CONTACT_FIELD_BINDING_OPTIONS}
              value={binding.field}
              onChange={(field) => onChange({ ...binding, field })}
              disabled={!editing}
              ariaLabel={`${label} field`}
            />
            <Input
              placeholder="Fallback"
              value={binding.fallback}
              onChange={(e) => onChange({ ...binding, fallback: e.target.value })}
              disabled={!editing}
              data-testid={`${testidPrefix}-fallback`}
            />
          </div>
        )}
      </div>
    </div>
  );
}

export interface BindingEditorProps {
  channelId: string;
  template: WhatsAppTemplate;
  editing: boolean;
  header: TemplateBinding[];
  body: TemplateBinding[];
  buttons: TemplateBinding[];
  onChangeHeader: (next: TemplateBinding[]) => void;
  onChangeBody: (next: TemplateBinding[]) => void;
  onChangeButtons: (next: TemplateBinding[]) => void;
}

export function BindingEditor({
  channelId,
  template,
  editing,
  header,
  body,
  buttons,
  onChangeHeader,
  onChangeBody,
  onChangeButtons,
}: BindingEditorProps) {
  const [doc, setDoc] = useState<WaTemplateDoc | null>(null);

  useEffect(() => {
    let active = true;
    whatsappTemplateService
      .get(channelId, template.id)
      .then((detail) => active && setDoc(detail.doc))
      .catch(() => active && setDoc(null));
    return () => {
      active = false;
    };
  }, [channelId, template.id]);

  const previewDoc: WaTemplateDoc | null = doc
    ? {
        ...doc,
        header:
          doc.header && doc.header.format === 'TEXT'
            ? { ...doc.header, example: previewText(header[0]) }
            : doc.header,
        body: { ...doc.body, examples: body.map((b) => previewText(b)) },
      }
    : null;

  const update = (list: TemplateBinding[], i: number, next: TemplateBinding, setter: (v: TemplateBinding[]) => void) => {
    const copy = [...list];
    copy[i] = next;
    setter(copy);
  };

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
      <div className="flex flex-col gap-3">
        <ClampedText text={`${template.name} (${template.language ?? 'default'})`} lines={1} className="text-sm font-medium" />
        {header.map((b, i) => (
          <BindingRow
            key={`header-${i}`}
            label={`Header {{${i + 1}}}`}
            binding={b}
            editing={editing}
            onChange={(next) => update(header, i, next, onChangeHeader)}
            testidPrefix={`broadcast-binding-header-${i}`}
          />
        ))}
        {body.map((b, i) => (
          <BindingRow
            key={`body-${i}`}
            label={`Body {{${i + 1}}}`}
            binding={b}
            editing={editing}
            onChange={(next) => update(body, i, next, onChangeBody)}
            testidPrefix={`broadcast-binding-body-${i}`}
          />
        ))}
        {buttons.map((b, i) => (
          <BindingRow
            key={`button-${i}`}
            label={`Button URL {{${i + 1}}}`}
            binding={b}
            editing={editing}
            onChange={(next) => update(buttons, i, next, onChangeButtons)}
            testidPrefix={`broadcast-binding-button-${i}`}
          />
        ))}
      </div>
      <div>{previewDoc && <WaBubblePreview doc={previewDoc} />}</div>
    </div>
  );
}
