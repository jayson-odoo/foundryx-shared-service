'use client';

import type { UseFormReturn } from 'react-hook-form';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { MergeInput } from '@/components/platform/email-editor';
import { SearchSelect } from '@/components/platform/search-select';
import { StatusBadge } from '@/components/platform/status-badge';
import type {
  Template,
  TemplateContext,
  TemplateContextFact,
} from '@/types/templates';
import { TEMPLATE_TIER_REGISTRY } from './template-tier';
import type { TemplateFormValues } from './use-template-form';

export interface TemplateSettingsFieldsProps {
  form: UseFormReturn<TemplateFormValues>;
  editing: boolean;
  isNew: boolean;
  template: Template | null;
  contexts: TemplateContext[];
  mergeFields: TemplateContextFact[];
}

function Row({ label, required, children }: { label: string; required?: boolean; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-1.5 md:grid-cols-[200px_1fr] md:items-start md:gap-4">
      <Label className="pt-2 text-sm text-muted-foreground">
        {label}
        {required && <span className="text-destructive"> *</span>}
      </Label>
      <div className="max-w-xl">{children}</div>
    </div>
  );
}

const TYPE_OPTIONS = [
  { label: 'Email', value: 'email' },
  { label: 'Document (PDF)', value: 'document' },
  { label: 'Badge / canvas', value: 'badge' },
];

/** Contexts belong to a surface — filter by the chosen type so the picker only
 * offers vocabularies that render on it (badge.* / document.* / everything-else
 * = email). Keeps the create flow foolproof (can't pair a badge with an email
 * context). */
function contextsForType(contexts: TemplateContext[], type: string): TemplateContext[] {
  if (type === 'badge') return contexts.filter((c) => c.key.startsWith('badge.'));
  if (type === 'document') return contexts.filter((c) => c.key.startsWith('document.'));
  return contexts.filter((c) => !c.key.startsWith('badge.') && !c.key.startsWith('document.'));
}

export function TemplateSettingsFields({
  form,
  editing,
  isNew,
  template,
  contexts,
  mergeFields,
}: TemplateSettingsFieldsProps) {
  const values = form.watch();
  const typeContexts = contextsForType(contexts, values.type);
  const isBadge = (isNew ? values.type : template?.type) === 'badge';

  return (
    <div className="flex flex-col gap-5 py-2">
      <Row label="Type" required>
        {/* Surface type is immutable after creation. */}
        {editing && isNew ? (
          <SearchSelect
            ariaLabel="Template type"
            options={TYPE_OPTIONS}
            value={values.type}
            onChange={(type) => form.setValue('type', type as TemplateFormValues['type'], { shouldDirty: true })}
          />
        ) : (
          <span className="text-sm capitalize">
            {template?.type === 'badge' ? 'Badge / canvas' : (template?.type ?? values.type)}
          </span>
        )}
      </Row>

      <Row label="Name" required>
        {editing ? (
          <Input
            aria-label="Template name"
            value={values.name}
            onChange={(e) => form.setValue('name', e.target.value, { shouldDirty: true })}
          />
        ) : (
          <span className="text-sm font-medium">{values.name || '—'}</span>
        )}
      </Row>

      {/* Badges render to a card, not an email — no subject line. */}
      {!isBadge && (
        <Row label="Subject" required>
          {editing ? (
            <MergeInput
              aria-label="Subject"
              value={values.subject}
              onChange={(subject) => form.setValue('subject', subject, { shouldDirty: true })}
              fields={mergeFields}
            />
          ) : (
            <span className="text-sm">{values.subject || '—'}</span>
          )}
        </Row>
      )}

      <Row label="Context" required>
        {/* Context is immutable after creation — it defines the fact vocabulary. */}
        {editing && isNew ? (
          <SearchSelect
            ariaLabel="Template context"
            options={typeContexts.map((c) => ({ label: c.label, value: c.key }))}
            value={values.context || null}
            onChange={(context) => form.setValue('context', context, { shouldDirty: true })}
            placeholder="Pick the context this template renders in…"
          />
        ) : (
          <span className="text-sm">
            {contexts.find((c) => c.key === values.context)?.label ?? values.context ?? '—'}
          </span>
        )}
      </Row>

      {!isNew && template && (
        <>
          <Row label="Key">
            <code className="text-xs text-muted-foreground">{template.key}</code>
          </Row>
          <Row label="Tier">
            <StatusBadge status={template.tier} registry={TEMPLATE_TIER_REGISTRY} size="sm" />
          </Row>
        </>
      )}

      {mergeFields.length > 0 && (
        <Row label="Available merge fields">
          <div className="flex flex-wrap gap-1.5">
            {mergeFields.map((f) => (
              <code key={f.key} className="rounded bg-muted px-1.5 py-0.5 text-xs">
                {`{{${f.key}}}`}
              </code>
            ))}
          </div>
        </Row>
      )}
    </div>
  );
}
