'use client';

/**
 * Contact panel - Details section (plan 25, AC-CDM-35/36). Read by default;
 * an Edit toggle switches every input on. Save sends ONE PATCH with only the
 * CHANGED keys (system fields + `customFields` partial merge - unregistered
 * keys are never touched); 422 `fieldErrors` map onto the offending input;
 * Cancel restores the last-saved values.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { Loader2, PencilLine } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { SearchSelect } from '@/components/platform/search-select';
import { ApiError } from '@/lib/api-client';
import { useCan } from '@/hooks/use-can';
import type { ContactField, ConversationThread, PatchContactInput } from '@/types/omnichannel';

export interface ContactDetailsFormProps {
  thread: ConversationThread;
  /** Registered custom fields for this workspace, in `sortOrder`. */
  fields: ContactField[];
  onSave: (patch: PatchContactInput) => Promise<unknown>;
}

type CustomFieldValue = string | number | boolean | null;
type SystemValues = {
  firstName: string;
  lastName: string;
  email: string;
  language: string;
  countryCode: string;
};

// `phone` is READ-ONLY - it is the inbound stitch key and is never writable
// through this PATCH (backend named 422 `fieldErrors.phone` if the wire key
// is even present, review round-1 finding). Never include it in `SystemValues`
// / the patch payload; render it as a plain read-only value below.
function systemValuesOf(thread: ConversationThread): SystemValues {
  return {
    firstName: thread.firstName ?? '',
    lastName: thread.lastName ?? '',
    email: thread.email ?? '',
    language: thread.language ?? '',
    countryCode: thread.countryCode ?? '',
  };
}

function customValuesOf(thread: ConversationThread, fields: ContactField[]): Record<string, CustomFieldValue> {
  const out: Record<string, CustomFieldValue> = {};
  for (const f of fields) {
    const raw = thread.customFields[f.key];
    out[f.key] = raw === undefined ? null : raw;
  }
  return out;
}

export function ContactDetailsForm({ thread, fields, onSave }: ContactDetailsFormProps) {
  const visibleFields = useMemo(
    () => fields.filter((f) => f.visibility === 'always').sort((a, b) => a.sortOrder - b.sortOrder),
    [fields],
  );

  const { can } = useCan();
  const canManage = can('contacts.manage');
  const [editing, setEditing] = useState(false);
  const [system, setSystem] = useState<SystemValues>(() => systemValuesOf(thread));
  const [custom, setCustom] = useState<Record<string, CustomFieldValue>>(() => customValuesOf(thread, fields));
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  // F3 (plan-25 round-3 codex triage): the values AT THE MOMENT Edit started
  // (or last reconciled for an untouched field) - Save diffs the draft
  // against THIS baseline, never the live `thread` prop, which keeps moving
  // from incoming `contact.updated` pushes while the agent is mid-edit.
  // `touchedRef` marks the keys the agent has actually typed into - only
  // those are ever allowed to diff away from the baseline.
  const baselineRef = useRef<{ system: SystemValues; custom: Record<string, CustomFieldValue> }>({
    system: systemValuesOf(thread),
    custom: customValuesOf(thread, fields),
  });
  const touchedSystemRef = useRef<Set<keyof SystemValues>>(new Set());
  const touchedCustomRef = useRef<Set<string>>(new Set());

  // A different contact (or a fresh server value after a save/WS push) resets
  // the form UNLESS the agent is mid-edit - and even then, ONLY the fields
  // the agent hasn't touched are refreshed (+ re-baselined) from the incoming
  // value; a touched field keeps exactly what the agent typed until
  // Save/Cancel, so a concurrent change to some OTHER field is reflected
  // live and never gets stomped by Save re-sending a stale value for it.
  useEffect(() => {
    const freshSystem = systemValuesOf(thread);
    const freshCustom = customValuesOf(thread, fields);
    if (!editing) {
      setSystem(freshSystem);
      setCustom(freshCustom);
      baselineRef.current = { system: freshSystem, custom: freshCustom };
      touchedSystemRef.current = new Set();
      touchedCustomRef.current = new Set();
      return;
    }
    setSystem((prev) => {
      let changed = false;
      const next = { ...prev };
      (Object.keys(freshSystem) as (keyof SystemValues)[]).forEach((key) => {
        if (!touchedSystemRef.current.has(key) && prev[key] !== freshSystem[key]) {
          next[key] = freshSystem[key];
          changed = true;
        }
      });
      return changed ? next : prev;
    });
    setCustom((prev) => {
      let changed = false;
      const next = { ...prev };
      for (const f of fields) {
        if (!touchedCustomRef.current.has(f.key) && prev[f.key] !== freshCustom[f.key]) {
          next[f.key] = freshCustom[f.key];
          changed = true;
        }
      }
      return changed ? next : prev;
    });
    const nextBaselineSystem = { ...baselineRef.current.system };
    (Object.keys(freshSystem) as (keyof SystemValues)[]).forEach((key) => {
      if (!touchedSystemRef.current.has(key)) nextBaselineSystem[key] = freshSystem[key];
    });
    const nextBaselineCustom = { ...baselineRef.current.custom };
    for (const f of fields) {
      if (!touchedCustomRef.current.has(f.key)) nextBaselineCustom[f.key] = freshCustom[f.key];
    }
    baselineRef.current = { system: nextBaselineSystem, custom: nextBaselineCustom };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [thread.id, thread.firstName, thread.lastName, thread.email, thread.language, thread.countryCode, thread.customFields, fields, editing]);

  const startEdit = () => {
    const freshSystem = systemValuesOf(thread);
    const freshCustom = customValuesOf(thread, fields);
    setSystem(freshSystem);
    setCustom(freshCustom);
    baselineRef.current = { system: freshSystem, custom: freshCustom };
    touchedSystemRef.current = new Set();
    touchedCustomRef.current = new Set();
    setFieldErrors({});
    setEditing(true);
  };
  const cancel = () => {
    setSystem(systemValuesOf(thread));
    setCustom(customValuesOf(thread, fields));
    setFieldErrors({});
    setEditing(false);
  };

  const save = async () => {
    setSaving(true);
    setFieldErrors({});
    try {
      const before = baselineRef.current.system;
      const patch: PatchContactInput = {};
      if (system.firstName !== before.firstName) patch.firstName = system.firstName || null;
      if (system.lastName !== before.lastName) patch.lastName = system.lastName || null;
      if (system.email !== before.email) patch.email = system.email || null;
      if (system.language !== before.language) patch.language = system.language || null;
      if (system.countryCode !== before.countryCode) patch.countryCode = system.countryCode || null;

      const beforeCustom = baselineRef.current.custom;
      const changedCustom: Record<string, CustomFieldValue> = {};
      let hasCustomChange = false;
      for (const f of fields) {
        if (custom[f.key] !== beforeCustom[f.key]) {
          changedCustom[f.key] = custom[f.key];
          hasCustomChange = true;
        }
      }
      if (hasCustomChange) patch.customFields = changedCustom;

      if (Object.keys(patch).length === 0) {
        setEditing(false);
        return;
      }
      await onSave(patch);
      setEditing(false);
    } catch (error) {
      if (error instanceof ApiError && error.status === 422) {
        const errs = (error.detail as { fieldErrors?: Record<string, string> } | undefined)?.fieldErrors;
        setFieldErrors(errs ?? { _: error.message });
      } else {
        setFieldErrors({ _: error instanceof Error ? error.message : 'Could not save the contact.' });
      }
    } finally {
      setSaving(false);
    }
  };

  const errorFor = (key: string) => fieldErrors[key];

  return (
    <div className="flex flex-col gap-3" data-testid="contact-details-form">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium text-muted-foreground uppercase">Details</p>
        {!editing ? (
          canManage && (
            <Button variant="ghost" size="sm" onClick={startEdit} data-testid="contact-details-edit">
              <PencilLine className="size-3.5" /> Edit
            </Button>
          )
        ) : (
          <div className="flex gap-1.5">
            <Button variant="ghost" size="sm" onClick={cancel} disabled={saving}>
              Cancel
            </Button>
            <Button variant="primary" size="sm" onClick={save} disabled={saving} data-testid="contact-details-save">
              {saving && <Loader2 className="size-3.5 animate-spin" />}
              Save
            </Button>
          </div>
        )}
      </div>

      {fieldErrors._ && <p className="text-xs text-destructive">{fieldErrors._}</p>}

      <div className="grid grid-cols-2 gap-x-2 gap-y-3">
        <div className="flex flex-col gap-1">
          <Label htmlFor="cd-first-name" className="text-xs text-muted-foreground">
            First name
          </Label>
          {editing ? (
            <Input
              id="cd-first-name"
              value={system.firstName}
              onChange={(e) => {
                touchedSystemRef.current.add('firstName');
                setSystem((s) => ({ ...s, firstName: e.target.value }));
              }}
              className="h-8"
            />
          ) : (
            <p className="text-sm">{thread.firstName || '-'}</p>
          )}
          {errorFor('firstName') && <p className="text-xs text-destructive">{errorFor('firstName')}</p>}
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="cd-last-name" className="text-xs text-muted-foreground">
            Last name
          </Label>
          {editing ? (
            <Input
              id="cd-last-name"
              value={system.lastName}
              onChange={(e) => {
                touchedSystemRef.current.add('lastName');
                setSystem((s) => ({ ...s, lastName: e.target.value }));
              }}
              className="h-8"
            />
          ) : (
            <p className="text-sm">{thread.lastName || '-'}</p>
          )}
          {errorFor('lastName') && <p className="text-xs text-destructive">{errorFor('lastName')}</p>}
        </div>

        <div className="flex flex-col gap-1">
          <Label id="cd-phone-label" className="text-xs text-muted-foreground">
            Phone
          </Label>
          {/* Read-only always - the backend never accepts `phone` on this
              PATCH (it's the inbound stitch key, review round-1 finding).
              No `htmlFor` here - a `<label for>` must reference a focusable
              form control, and this value is a plain `<p>`; `aria-labelledby`
              is the correct association for a non-control value (review
              round 2, finding J). */}
          <p aria-labelledby="cd-phone-label" className="text-sm">
            {thread.phone || '-'}
          </p>
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="cd-email" className="text-xs text-muted-foreground">
            Email
          </Label>
          {editing ? (
            <Input
              id="cd-email"
              type="email"
              value={system.email}
              onChange={(e) => {
                touchedSystemRef.current.add('email');
                setSystem((s) => ({ ...s, email: e.target.value }));
              }}
              className="h-8"
            />
          ) : (
            <p className="text-sm">{thread.email || '-'}</p>
          )}
          {errorFor('email') && <p className="text-xs text-destructive">{errorFor('email')}</p>}
        </div>

        <div className="flex flex-col gap-1">
          <Label htmlFor="cd-language" className="text-xs text-muted-foreground">
            Language
          </Label>
          {editing ? (
            <Input
              id="cd-language"
              placeholder="en"
              value={system.language}
              onChange={(e) => {
                touchedSystemRef.current.add('language');
                setSystem((s) => ({ ...s, language: e.target.value }));
              }}
              className="h-8"
            />
          ) : (
            <p className="text-sm">{thread.language || '-'}</p>
          )}
          {errorFor('language') && <p className="text-xs text-destructive">{errorFor('language')}</p>}
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="cd-country" className="text-xs text-muted-foreground">
            Country
          </Label>
          {editing ? (
            <Input
              id="cd-country"
              placeholder="MY"
              maxLength={2}
              value={system.countryCode}
              onChange={(e) => {
                touchedSystemRef.current.add('countryCode');
                setSystem((s) => ({ ...s, countryCode: e.target.value.toUpperCase() }));
              }}
              className="h-8 uppercase"
            />
          ) : (
            <p className="text-sm">{thread.countryCode || '-'}</p>
          )}
          {errorFor('countryCode') && <p className="text-xs text-destructive">{errorFor('countryCode')}</p>}
        </div>

        {visibleFields.map((f) => (
          <div key={f.id} className="flex flex-col gap-1">
            <Label htmlFor={`cd-cf-${f.id}`} className="text-xs text-muted-foreground">
              {f.label}
            </Label>
            <CustomFieldInput
              field={f}
              editing={editing}
              value={custom[f.key] ?? null}
              onChange={(v) => {
                touchedCustomRef.current.add(f.key);
                setCustom((c) => ({ ...c, [f.key]: v }));
              }}
            />
            {errorFor(`customFields.${f.key}`) && (
              <p className="text-xs text-destructive">{errorFor(`customFields.${f.key}`)}</p>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function CustomFieldInput({
  field,
  editing,
  value,
  onChange,
}: {
  field: ContactField;
  editing: boolean;
  value: CustomFieldValue;
  onChange: (value: CustomFieldValue) => void;
}) {
  const id = `cd-cf-${field.id}`;
  if (!editing) {
    if (field.type === 'checkbox') return <p className="text-sm">{value ? 'Yes' : 'No'}</p>;
    return <p className="text-sm">{value === null || value === undefined || value === '' ? '-' : String(value)}</p>;
  }

  switch (field.type) {
    case 'list':
      return (
        <SearchSelect
          options={(field.options ?? []).map((o) => ({ label: o, value: o }))}
          value={typeof value === 'string' ? value : null}
          onChange={(v) => onChange(v)}
          ariaLabel={field.label}
        />
      );
    case 'checkbox':
      return (
        <div className="flex h-8 items-center">
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
          className="h-8"
        />
      );
    case 'date':
      return (
        <Input
          id={id}
          type="date"
          value={typeof value === 'string' ? value : ''}
          onChange={(e) => onChange(e.target.value || null)}
          className="h-8"
        />
      );
    case 'time':
      return (
        <Input
          id={id}
          type="time"
          value={typeof value === 'string' ? value : ''}
          onChange={(e) => onChange(e.target.value || null)}
          className="h-8"
        />
      );
    case 'url':
      return (
        <Input
          id={id}
          type="url"
          value={typeof value === 'string' ? value : ''}
          onChange={(e) => onChange(e.target.value || null)}
          className="h-8"
        />
      );
    case 'email':
      return (
        <Input
          id={id}
          type="email"
          value={typeof value === 'string' ? value : ''}
          onChange={(e) => onChange(e.target.value || null)}
          className="h-8"
        />
      );
    default: // text
      return (
        <Input
          id={id}
          value={typeof value === 'string' ? value : ''}
          onChange={(e) => onChange(e.target.value || null)}
          className="h-8"
        />
      );
  }
}
