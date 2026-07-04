'use client';

/** Settings tab (plan sprint-3/01 D10/D11/D18) — access, submission window,
 * caps, per-user limit, display mode, pinned answer columns. Per-user limit
 * is enforceable only with an authenticated identity, so it greys out for
 * public forms (anonymous respondents — foolproof-UI, D10); `portal` access
 * is reserved for Cluster D and not offered yet (D11). */
import type { FieldPath, FieldPathValue, UseFormReturn } from 'react-hook-form';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { MultiSelect } from '@/components/platform/multi-select';
import { SearchSelect } from '@/components/platform/search-select';
import { useDatetime } from '@/hooks/use-datetime';
import { inputFields } from '@/lib/form-doc';
import type { FormDetail, FormDocument } from '@/types/forms';

export interface FormSettingsValues {
  name: string;
  description: string;
  access: 'internal' | 'public';
  opensAt: string;
  closesAt: string;
  maxSubmissions: string;
  submissionLimitPerUser: string;
  displayMode: 'paged' | 'single';
  pinnedColumns: string[];
  allowRevisions: boolean;
}

function Row({
  label,
  required,
  children,
}: {
  label: string;
  required?: boolean;
  children: React.ReactNode;
}) {
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

/** ISO → the value an <input type="datetime-local"> expects (local, no Z). */
function toLocalInput(iso: string): string {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export interface FormSettingsTabProps {
  form: UseFormReturn<FormSettingsValues>;
  editing: boolean;
  formRecord: FormDetail | null;
  doc: FormDocument;
}

export function FormSettingsTab({ form, editing, formRecord, doc }: FormSettingsTabProps) {
  const values = form.watch();
  const { formatDateTime } = useDatetime();
  const set = <K extends FieldPath<FormSettingsValues>>(
    key: K,
    value: FieldPathValue<FormSettingsValues, K>,
  ) => form.setValue(key, value, { shouldDirty: true });

  const columnOptions = inputFields(doc)
    .filter((f) => f.key)
    .map((f) => ({ value: f.key as string, label: f.label || (f.key as string) }));

  return (
    <div className="flex flex-col gap-5 py-2">
      <Row label="Name" required>
        {editing ? (
          <Input
            aria-label="Form name"
            value={values.name}
            onChange={(e) => set('name', e.target.value)}
          />
        ) : (
          <span className="text-sm font-medium">{values.name || '—'}</span>
        )}
      </Row>

      <Row label="Description">
        {editing ? (
          <Input
            aria-label="Form description"
            value={values.description}
            onChange={(e) => set('description', e.target.value)}
          />
        ) : (
          <span className="text-sm text-muted-foreground">{values.description || '—'}</span>
        )}
      </Row>

      <Row label="Access">
        {editing ? (
          <SearchSelect
            value={values.access}
            onChange={(v) => set('access', (v as 'internal' | 'public') || 'internal')}
            options={[
              { value: 'internal', label: 'Internal — signed-in users' },
              { value: 'public', label: 'Public — anyone with the link' },
            ]}
            placeholder="Access"
          />
        ) : (
          <span className="text-sm">{values.access === 'public' ? 'Public' : 'Internal'}</span>
        )}
      </Row>

      <Row label="Opens at">
        {editing ? (
          <Input
            type="datetime-local"
            aria-label="Opens at"
            value={toLocalInput(values.opensAt)}
            onChange={(e) =>
              set('opensAt', e.target.value ? new Date(e.target.value).toISOString() : '')
            }
          />
        ) : (
          <span className="text-sm text-muted-foreground">
            {values.opensAt ? formatDateTime(values.opensAt) : 'Immediately'}
          </span>
        )}
      </Row>

      <Row label="Closes at">
        {editing ? (
          <Input
            type="datetime-local"
            aria-label="Closes at"
            value={toLocalInput(values.closesAt)}
            onChange={(e) =>
              set('closesAt', e.target.value ? new Date(e.target.value).toISOString() : '')
            }
          />
        ) : (
          <span className="text-sm text-muted-foreground">
            {values.closesAt ? formatDateTime(values.closesAt) : 'Never'}
          </span>
        )}
      </Row>

      <Row label="Max submissions">
        {editing ? (
          <Input
            type="number"
            min={1}
            aria-label="Max submissions"
            value={values.maxSubmissions}
            onChange={(e) => set('maxSubmissions', e.target.value)}
            placeholder="Unlimited"
          />
        ) : (
          <span className="text-sm text-muted-foreground">{values.maxSubmissions || 'Unlimited'}</span>
        )}
      </Row>

      <Row label="Limit per user">
        {editing ? (
          <Input
            type="number"
            min={1}
            aria-label="Submission limit per user"
            value={values.submissionLimitPerUser}
            onChange={(e) => set('submissionLimitPerUser', e.target.value)}
            placeholder="Unlimited"
            disabled={values.access === 'public'}
          />
        ) : (
          <span className="text-sm text-muted-foreground">
            {values.access === 'public' ? '—' : values.submissionLimitPerUser || 'Unlimited'}
          </span>
        )}
      </Row>

      <Row label="Display">
        {editing ? (
          <SearchSelect
            value={values.displayMode}
            onChange={(v) => set('displayMode', (v as 'paged' | 'single') || 'paged')}
            options={[
              { value: 'paged', label: 'One page per step' },
              { value: 'single', label: 'Single scrolling page' },
            ]}
            placeholder="Display"
          />
        ) : (
          <span className="text-sm">
            {values.displayMode === 'single' ? 'Single scrolling page' : 'One page per step'}
          </span>
        )}
      </Row>

      <Row label="Answer columns">
        {editing ? (
          <MultiSelect
            value={values.pinnedColumns}
            onChange={(v) => set('pinnedColumns', v)}
            options={columnOptions}
            placeholder="Pick answers to show as columns"
          />
        ) : (
          <span className="text-sm text-muted-foreground">
            {values.pinnedColumns.length
              ? values.pinnedColumns
                  .map((k) => columnOptions.find((o) => o.value === k)?.label ?? k)
                  .join(', ')
              : 'None'}
          </span>
        )}
      </Row>

      <Row label="Allow revisions">
        {editing ? (
          <div className="flex items-center gap-2 pt-1.5">
            <Switch
              checked={values.allowRevisions}
              onCheckedChange={(checked) => set('allowRevisions', checked)}
              aria-label="Allow revisions"
            />
            <span className="text-sm text-muted-foreground">
              Authors can revise a submitted entry into a new version.
            </span>
          </div>
        ) : (
          <span className="text-sm">{values.allowRevisions ? 'Enabled' : 'Disabled'}</span>
        )}
      </Row>

      {formRecord && (
        <Row label="Slug">
          <span className="text-sm text-muted-foreground">{formRecord.slug}</span>
        </Row>
      )}
    </div>
  );
}
