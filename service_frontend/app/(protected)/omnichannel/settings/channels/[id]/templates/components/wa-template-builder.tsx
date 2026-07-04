'use client';

import { useRef, useState } from 'react';
import { Plus, Trash2, Loader2, Variable } from 'lucide-react';
import { toast } from 'sonner';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { SearchSelect } from '@/components/platform/search-select';
import { whatsappTemplateService } from '@/services/whatsapp-template-service';
import {
  TEMPLATE_CATEGORIES,
  TEMPLATE_LANGUAGES,
  BUTTON_TYPES,
  MAX_BUTTONS,
  distinctVarCount,
} from '@/lib/whatsapp-template';
import type { ButtonType, WaButton, WaTemplateDoc } from '@/types/whatsapp-template';

const HEADER_OPTIONS = [
  { value: 'NONE', label: 'None' },
  { value: 'TEXT', label: 'Text' },
  { value: 'IMAGE', label: 'Image' },
  { value: 'VIDEO', label: 'Video' },
  { value: 'DOCUMENT', label: 'Document' },
];
const BUTTON_TYPE_LABELS: Record<ButtonType, string> = {
  QUICK_REPLY: 'Quick reply',
  URL: 'URL',
  PHONE_NUMBER: 'Phone number',
  COPY_CODE: 'Copy code',
};

export interface WaTemplateBuilderProps {
  channelId: string;
  doc: WaTemplateDoc;
  onChange: (doc: WaTemplateDoc) => void;
  errors: Record<string, string>;
  disabled?: boolean;
  /** name/category/language are locked once the template is synced (edit). */
  identityLocked?: boolean;
}

function FieldError({ msg }: { msg?: string }) {
  if (!msg) return null;
  return <p className="mt-1 text-xs text-destructive">{msg}</p>;
}

export function WaTemplateBuilder({
  channelId,
  doc,
  onChange,
  errors,
  disabled = false,
  identityLocked = false,
}: WaTemplateBuilderProps) {
  const bodyRef = useRef<HTMLTextAreaElement>(null);
  const [uploading, setUploading] = useState(false);
  const set = (patch: Partial<WaTemplateDoc>) => onChange({ ...doc, ...patch });

  const headerType: string = doc.header?.format ?? 'NONE';
  const bodyVarCount = distinctVarCount(doc.body.text);

  const setHeaderType = (t: string) => {
    if (t === 'NONE') set({ header: null });
    else if (t === 'TEXT') set({ header: { format: 'TEXT', text: '', example: null } });
    else set({ header: { format: t as 'IMAGE' | 'VIDEO' | 'DOCUMENT', sampleKey: null } });
  };

  const insertVar = () => {
    const next = bodyVarCount + 1;
    const examples = [...doc.body.examples];
    examples[next - 1] = examples[next - 1] ?? '';
    set({ body: { text: `${doc.body.text}{{${next}}}`, examples } });
  };

  const setBodyText = (text: string) => {
    const n = distinctVarCount(text);
    const examples = doc.body.examples.slice(0, n);
    while (examples.length < n) examples.push('');
    set({ body: { text, examples } });
  };

  const setExample = (i: number, v: string) => {
    const examples = [...doc.body.examples];
    examples[i] = v;
    set({ body: { ...doc.body, examples } });
  };

  const onPickMedia = async (file: File | undefined) => {
    if (!file) return;
    setUploading(true);
    try {
      const { sampleKey } = await whatsappTemplateService.uploadSample(channelId, file);
      if (doc.header && doc.header.format !== 'TEXT') {
        set({ header: { ...doc.header, sampleKey } });
        toast.success(`Sample “${file.name}” attached.`);
      }
    } catch {
      toast.error('Unsupported file or upload failed (images or PDF only).');
    } finally {
      setUploading(false);
    }
  };

  const buttons = doc.buttons ?? [];
  const setButton = (i: number, patch: Partial<WaButton>) => {
    const next = buttons.map((b, idx) => (idx === i ? { ...b, ...patch } : b));
    set({ buttons: next });
  };
  const addButton = () => set({ buttons: [...buttons, { type: 'QUICK_REPLY', text: '' }] });
  const removeButton = (i: number) =>
    set({ buttons: buttons.filter((_, idx) => idx !== i).length ? buttons.filter((_, idx) => idx !== i) : null });

  return (
    <div className="flex flex-col gap-5">
      {/* Identity */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <Label>Name</Label>
          <Input
            value={doc.name}
            disabled={disabled || identityLocked}
            placeholder="order_update"
            onChange={(e) => set({ name: e.target.value })}
          />
          <FieldError msg={errors.name} />
        </div>
        <div>
          <Label>Category</Label>
          <SearchSelect
            options={TEMPLATE_CATEGORIES.map((c) => ({ value: c, label: c === 'MARKETING' ? 'Marketing' : 'Utility' }))}
            value={doc.category}
            onChange={(v) => set({ category: v as 'MARKETING' | 'UTILITY' })}
            disabled={disabled || identityLocked}
            ariaLabel="Category"
          />
          <FieldError msg={errors.category} />
        </div>
        <div>
          <Label>Language</Label>
          <SearchSelect
            options={TEMPLATE_LANGUAGES.map((l) => ({ value: l, label: l }))}
            value={doc.language}
            onChange={(v) => set({ language: v })}
            disabled={disabled || identityLocked}
            ariaLabel="Language"
          />
          <FieldError msg={errors.language} />
        </div>
      </div>

      {/* Header */}
      <div>
        <Label>Header</Label>
        <SearchSelect
          options={HEADER_OPTIONS}
          value={headerType}
          onChange={setHeaderType}
          disabled={disabled}
          ariaLabel="Header type"
        />
        {doc.header?.format === 'TEXT' && (
          <div className="mt-2 flex flex-col gap-2">
            <Input
              value={doc.header.text}
              disabled={disabled}
              placeholder="Header text (one {{1}} variable allowed)"
              onChange={(e) =>
                set({ header: { format: 'TEXT', text: e.target.value, example: doc.header && 'example' in doc.header ? doc.header.example : null } })
              }
            />
            {distinctVarCount(doc.header.text) === 1 && (
              <Input
                value={doc.header.example ?? ''}
                disabled={disabled}
                placeholder="Sample value for the header variable"
                onChange={(e) => set({ header: { format: 'TEXT', text: (doc.header as { text: string }).text, example: e.target.value } })}
              />
            )}
          </div>
        )}
        {doc.header && doc.header.format !== 'TEXT' && (
          <div className="mt-2 flex items-center gap-2">
            <Input
              type="file"
              accept="image/*,application/pdf"
              disabled={disabled || uploading}
              onChange={(e) => onPickMedia(e.target.files?.[0])}
            />
            {uploading && <Loader2 className="size-4 animate-spin" />}
            {doc.header.sampleKey && <span className="text-xs text-success">Sample attached</span>}
          </div>
        )}
        <FieldError msg={errors.header} />
      </div>

      {/* Body */}
      <div>
        <div className="flex items-center justify-between">
          <Label>Body</Label>
          <Button type="button" variant="ghost" size="sm" disabled={disabled} onClick={insertVar}>
            <Variable className="size-4" /> Add variable
          </Button>
        </div>
        <Textarea
          ref={bodyRef}
          rows={4}
          value={doc.body.text}
          disabled={disabled}
          placeholder="Hi {{1}}, your order {{2}} is on the way."
          onChange={(e) => setBodyText(e.target.value)}
        />
        <FieldError msg={errors.body} />
        {bodyVarCount > 0 && (
          <div className="mt-2 flex flex-col gap-2">
            {Array.from({ length: bodyVarCount }).map((_, i) => (
              <div key={i} className="flex items-center gap-2">
                <span className="w-12 text-xs text-muted-foreground">{`{{${i + 1}}}`}</span>
                <Input
                  value={doc.body.examples[i] ?? ''}
                  disabled={disabled}
                  placeholder={`Sample for {{${i + 1}}}`}
                  onChange={(e) => setExample(i, e.target.value)}
                />
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Footer */}
      <div>
        <Label>Footer (optional)</Label>
        <Input
          value={doc.footer?.text ?? ''}
          disabled={disabled}
          placeholder="e.g. Reply STOP to opt out"
          onChange={(e) => set({ footer: e.target.value ? { text: e.target.value } : null })}
        />
      </div>

      {/* Buttons */}
      <div>
        <div className="flex items-center justify-between">
          <Label>Buttons (optional)</Label>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={disabled || buttons.length >= MAX_BUTTONS}
            onClick={addButton}
          >
            <Plus className="size-4" /> Add button
          </Button>
        </div>
        <FieldError msg={errors.buttons} />
        <div className="mt-2 flex flex-col gap-3">
          {buttons.map((b, i) => (
            <div key={i} className="rounded-md border border-border p-3">
              <div className="flex items-center gap-2">
                <SearchSelect
                  options={BUTTON_TYPES.map((t) => ({ value: t, label: BUTTON_TYPE_LABELS[t] }))}
                  value={b.type}
                  onChange={(v) => setButton(i, { type: v as ButtonType })}
                  disabled={disabled}
                  ariaLabel={`Button ${i + 1} type`}
                  className="max-w-[180px]"
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  disabled={disabled}
                  onClick={() => removeButton(i)}
                  aria-label={`Remove button ${i + 1}`}
                >
                  <Trash2 className="size-4" />
                </Button>
              </div>
              <div className="mt-2 flex flex-col gap-2">
                {b.type !== 'COPY_CODE' && (
                  <Input
                    value={b.text ?? ''}
                    disabled={disabled}
                    placeholder="Button label"
                    onChange={(e) => setButton(i, { text: e.target.value })}
                  />
                )}
                {b.type === 'URL' && (
                  <>
                    <Input
                      value={b.url ?? ''}
                      disabled={disabled}
                      placeholder="https://example.com/{{1}}"
                      onChange={(e) => setButton(i, { url: e.target.value })}
                    />
                    {distinctVarCount(b.url ?? '') === 1 && (
                      <Input
                        value={b.example ?? ''}
                        disabled={disabled}
                        placeholder="Sample value for the dynamic URL"
                        onChange={(e) => setButton(i, { example: e.target.value })}
                      />
                    )}
                  </>
                )}
                {b.type === 'PHONE_NUMBER' && (
                  <Input
                    value={b.phoneNumber ?? ''}
                    disabled={disabled}
                    placeholder="+60123456789"
                    onChange={(e) => setButton(i, { phoneNumber: e.target.value })}
                  />
                )}
                {b.type === 'COPY_CODE' && (
                  <Input
                    value={b.example ?? ''}
                    disabled={disabled}
                    placeholder="Sample code, e.g. SAVE10"
                    onChange={(e) => setButton(i, { example: e.target.value })}
                  />
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
