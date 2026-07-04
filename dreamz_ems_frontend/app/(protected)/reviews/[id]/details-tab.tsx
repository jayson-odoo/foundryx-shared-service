'use client';

/**
 * Details tab of the Review-process detail form (AC-06-38/55/56). Form + window
 * + required count + the only-valid-option pickers:
 *   - scoreFieldKey  → ONLY numeric fields of the review form's published
 *                      version (warns when the review form has none) — AC-06-55.
 *   - 4 status maps  → ONLY the submission form's scoped statuses — AC-06-55.
 * No how-to copy; every dropdown is a SearchSelect (AC-06-56).
 */
import { AlertTriangle } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { Badge } from '@/components/ui/badge';
import { SearchSelect, type SearchSelectOption } from '@/components/platform/search-select';
import { useDatetime } from '@/hooks/use-datetime';
import type { ReviewConfigMeta } from '@/types/review';

export interface DetailsValues {
  name: string;
  formId: string;
  reviewFormId: string;
  requiredReviewCount: number;
  scoreFieldKey: string | null;
  windowStart: string | null;
  windowEnd: string | null;
  reviewStartStatusId: string | null;
  revisionsStatusId: string | null;
  acceptedStatusId: string | null;
  rejectedStatusId: string | null;
  isActive: boolean;
}

/** ISO → datetime-local value (local, no Z) — house convention (form settings). */
function toLocalInput(iso: string | null): string {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-1.5 md:grid-cols-[220px_1fr] md:items-start md:gap-4">
      <Label className="pt-2 text-sm text-muted-foreground">{label}</Label>
      <div className="max-w-xl">{children}</div>
    </div>
  );
}

export interface DetailsTabProps {
  values: DetailsValues;
  onChange: (next: Partial<DetailsValues>) => void;
  editing: boolean;
  meta: ReviewConfigMeta;
  formOptions: SearchSelectOption[];
}

export function DetailsTab({
  values,
  onChange,
  editing,
  meta,
  formOptions,
}: DetailsTabProps) {
  const { formatDateTime } = useDatetime();
  const statusOptions: SearchSelectOption[] = meta.submissionStatuses.map((s) => ({
    value: s.id,
    label: s.label,
  }));
  const scoreOptions: SearchSelectOption[] = meta.numericFields.map((f) => ({
    value: f.key,
    label: f.label,
  }));
  const noNumeric = Boolean(values.reviewFormId) && meta.numericFields.length === 0;

  const statusLabel = (id: string | null) =>
    id ? meta.submissionStatuses.find((s) => s.id === id)?.label ?? id : '—';
  const formLabel = (id: string) => formOptions.find((o) => o.value === id)?.label ?? id;

  return (
    <div className="flex flex-col gap-5 py-2">
      <Row label="Name">
        {editing ? (
          <Input
            aria-label="Name"
            value={values.name}
            onChange={(e) => onChange({ name: e.target.value })}
          />
        ) : (
          <span className="text-sm font-medium">{values.name || '—'}</span>
        )}
      </Row>

      <Row label="Submission form">
        {editing ? (
          <SearchSelect
            ariaLabel="Submission form"
            value={values.formId}
            onChange={(v) => onChange({ formId: v })}
            options={formOptions}
            placeholder="Pick a form…"
          />
        ) : (
          <span className="text-sm">{formLabel(values.formId)}</span>
        )}
      </Row>

      <Row label="Review form">
        {editing ? (
          <SearchSelect
            ariaLabel="Review form"
            value={values.reviewFormId}
            onChange={(v) => onChange({ reviewFormId: v, scoreFieldKey: null })}
            options={formOptions}
            placeholder="Pick a form…"
          />
        ) : (
          <span className="text-sm">{formLabel(values.reviewFormId)}</span>
        )}
      </Row>

      <Row label="Required reviews">
        {editing ? (
          <Input
            type="number"
            min={1}
            aria-label="Required reviews"
            value={String(values.requiredReviewCount)}
            onChange={(e) =>
              onChange({ requiredReviewCount: Math.max(1, Number(e.target.value) || 1) })
            }
            className="w-28"
          />
        ) : (
          <span className="text-sm">{values.requiredReviewCount}</span>
        )}
      </Row>

      <Row label="Score field">
        {editing ? (
          <div className="space-y-2">
            <SearchSelect
              ariaLabel="Score field"
              value={values.scoreFieldKey}
              onChange={(v) => onChange({ scoreFieldKey: v })}
              options={scoreOptions}
              placeholder="Pick a numeric field…"
              disabled={noNumeric}
            />
            {noNumeric && (
              <div
                role="alert"
                className="flex items-start gap-2 rounded-md border border-[var(--color-warning-soft,var(--color-yellow-200))] bg-[var(--color-warning-soft,var(--color-yellow-50))] p-2.5 text-xs text-[var(--color-warning-accent,var(--color-yellow-700))]"
              >
                <AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
                <span>The review form has no numeric field in its published version.</span>
              </div>
            )}
          </div>
        ) : (
          <span className="text-sm">
            {values.scoreFieldKey
              ? scoreOptions.find((o) => o.value === values.scoreFieldKey)?.label ??
                values.scoreFieldKey
              : '—'}
          </span>
        )}
      </Row>

      <Row label="Window start">
        {editing ? (
          <Input
            type="datetime-local"
            aria-label="Window start"
            value={toLocalInput(values.windowStart)}
            onChange={(e) =>
              onChange({
                windowStart: e.target.value ? new Date(e.target.value).toISOString() : null,
              })
            }
          />
        ) : (
          <span className="text-sm">
            {values.windowStart ? formatDateTime(values.windowStart) : '—'}
          </span>
        )}
      </Row>

      <Row label="Window end">
        {editing ? (
          <Input
            type="datetime-local"
            aria-label="Window end"
            value={toLocalInput(values.windowEnd)}
            onChange={(e) =>
              onChange({
                windowEnd: e.target.value ? new Date(e.target.value).toISOString() : null,
              })
            }
          />
        ) : (
          <span className="text-sm">
            {values.windowEnd ? formatDateTime(values.windowEnd) : '—'}
          </span>
        )}
      </Row>

      <div className="border-t border-border pt-4">
        <p className="mb-3 text-sm font-medium">Status mapping</p>
        <div className="flex flex-col gap-4">
          <StatusMapRow
            label="Review start"
            value={values.reviewStartStatusId}
            editing={editing}
            options={statusOptions}
            readLabel={statusLabel(values.reviewStartStatusId)}
            onChange={(v) => onChange({ reviewStartStatusId: v })}
          />
          <StatusMapRow
            label="Revisions"
            value={values.revisionsStatusId}
            editing={editing}
            options={statusOptions}
            readLabel={statusLabel(values.revisionsStatusId)}
            onChange={(v) => onChange({ revisionsStatusId: v })}
          />
          <StatusMapRow
            label="Accepted"
            value={values.acceptedStatusId}
            editing={editing}
            options={statusOptions}
            readLabel={statusLabel(values.acceptedStatusId)}
            onChange={(v) => onChange({ acceptedStatusId: v })}
          />
          <StatusMapRow
            label="Rejected"
            value={values.rejectedStatusId}
            editing={editing}
            options={statusOptions}
            readLabel={statusLabel(values.rejectedStatusId)}
            onChange={(v) => onChange({ rejectedStatusId: v })}
          />
        </div>
      </div>

      <Row label="Active">
        <div className="flex items-center gap-2 pt-1">
          {editing ? (
            <Switch
              aria-label="Active"
              checked={values.isActive}
              onCheckedChange={(v) => onChange({ isActive: v })}
            />
          ) : (
            <Badge variant={values.isActive ? 'success' : 'secondary'} appearance="light" size="sm">
              {values.isActive ? 'Active' : 'Inactive'}
            </Badge>
          )}
        </div>
      </Row>
    </div>
  );
}

function StatusMapRow({
  label,
  value,
  editing,
  options,
  readLabel,
  onChange,
}: {
  label: string;
  value: string | null;
  editing: boolean;
  options: SearchSelectOption[];
  readLabel: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="grid grid-cols-1 gap-1.5 md:grid-cols-[220px_1fr] md:items-center md:gap-4">
      <Label className="text-sm text-muted-foreground">{label}</Label>
      <div className="max-w-xl">
        {editing ? (
          <SearchSelect
            ariaLabel={`${label} status`}
            value={value}
            onChange={onChange}
            options={options}
            placeholder="Pick a status…"
          />
        ) : (
          <span className="text-sm">{readLabel}</span>
        )}
      </div>
    </div>
  );
}
