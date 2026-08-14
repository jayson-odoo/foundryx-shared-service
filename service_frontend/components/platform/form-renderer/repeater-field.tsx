'use client';

/**
 * Repeater field (plan sprint-3/01) - a card per row of author-defined
 * sub-fields, with Add/Remove honouring `minRows`/`maxRows`. The answer is a
 * `Record<string, FormAnswerScalar>[]`; per-row errors arrive keyed
 * `key.rowIndex.subKey` (validation contract). Sub-fields are the restricted
 * scalar set (no composites/conditions, BL-089) so each row reuses the simple
 * scalar inputs.
 */
import { Plus, Trash2 } from 'lucide-react';
import { SearchSelect } from '@/components/platform/search-select';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';
import { RequiredMark } from '@/components/platform/resource-form/form-row';
import { RatingInput } from './rating-input';
import type {
  FormAnswerScalar,
  FormFieldErrors,
  FormSubField,
} from '@/types/forms';

type Row = Record<string, FormAnswerScalar>;

export interface RepeaterFieldProps {
  subFields: FormSubField[];
  minRows?: number;
  maxRows?: number;
  value: Row[];
  onChange: (rows: Row[]) => void;
  /** All form errors - this field reads its own `key.row.subKey` entries. */
  errors: FormFieldErrors;
  fieldKey: string;
  disabled?: boolean;
  idBase: string;
}

function blankRow(subs: FormSubField[]): Row {
  const row: Row = {};
  for (const sub of subs) row[sub.key] = sub.type === 'yesno' ? false : sub.type === 'rating' ? 0 : '';
  return row;
}

export function RepeaterField({
  subFields,
  minRows,
  maxRows,
  value,
  onChange,
  errors,
  fieldKey,
  disabled,
  idBase,
}: RepeaterFieldProps) {
  const rows = Array.isArray(value) ? value : [];
  const canAdd = maxRows == null || rows.length < maxRows;
  const canRemove = (count: number) => count > (minRows ?? 0);

  const setCell = (rowIndex: number, subKey: string, cell: FormAnswerScalar) => {
    const next = rows.map((r, i) => (i === rowIndex ? { ...r, [subKey]: cell } : r));
    onChange(next);
  };
  const addRow = () => onChange([...rows, blankRow(subFields)]);
  const removeRow = (rowIndex: number) => onChange(rows.filter((_, i) => i !== rowIndex));

  return (
    <div className="space-y-3">
      {rows.map((row, rowIndex) => (
        <div key={rowIndex} className="rounded-md border border-border p-3">
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
            {subFields.map((sub) => {
              const errorKey = `${fieldKey}.${rowIndex}.${sub.key}`;
              const error = errors[errorKey];
              const id = `${idBase}-${rowIndex}-${sub.key}`;
              return (
                <div key={sub.id} className="space-y-1">
                  <Label htmlFor={id} variant="secondary">
                    {sub.label}
                    {sub.required && <RequiredMark />}
                  </Label>
                  <SubFieldInput
                    sub={sub}
                    id={id}
                    value={row[sub.key]}
                    invalid={Boolean(error)}
                    disabled={disabled}
                    onChange={(cell) => setCell(rowIndex, sub.key, cell)}
                  />
                  {error && <p className="text-xs text-destructive">{error}</p>}
                </div>
              );
            })}
          </div>
          {!disabled && canRemove(rows.length) && (
            <div className="mt-3 flex justify-end">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => removeRow(rowIndex)}
                aria-label={`Remove item ${rowIndex + 1}`}
              >
                <Trash2 className="size-4" />
                Remove
              </Button>
            </div>
          )}
        </div>
      ))}
      {!disabled && (
        <Button type="button" variant="outline" size="sm" onClick={addRow} disabled={!canAdd}>
          <Plus className="size-4" />
          Add item
        </Button>
      )}
    </div>
  );
}

interface SubFieldInputProps {
  sub: FormSubField;
  id: string;
  value: FormAnswerScalar;
  onChange: (value: FormAnswerScalar) => void;
  invalid?: boolean;
  disabled?: boolean;
}

function SubFieldInput({ sub, id, value, onChange, invalid, disabled }: SubFieldInputProps) {
  const common = { id, disabled, 'aria-invalid': invalid || undefined };
  switch (sub.type) {
    case 'textarea':
      return (
        <Textarea
          {...common}
          value={String(value ?? '')}
          placeholder={sub.placeholder}
          onChange={(e) => onChange(e.target.value)}
        />
      );
    case 'number':
      return (
        <Input
          {...common}
          type="number"
          value={value === null || value === undefined ? '' : String(value)}
          placeholder={sub.placeholder}
          onChange={(e) => onChange(e.target.value === '' ? '' : Number(e.target.value))}
        />
      );
    case 'date':
      return (
        <Input
          {...common}
          type="date"
          value={String(value ?? '')}
          onChange={(e) => onChange(e.target.value)}
        />
      );
    case 'select':
    case 'radio':
      return (
        <SearchSelect
          options={(sub.options?.items ?? []).map((o) => ({ value: o.value, label: o.label }))}
          value={value == null ? null : String(value)}
          disabled={disabled}
          ariaLabel={sub.label}
          onChange={(v) => onChange(v)}
        />
      );
    case 'yesno':
      return (
        <SearchSelect
          options={[
            { value: 'true', label: 'Yes' },
            { value: 'false', label: 'No' },
          ]}
          value={value === true ? 'true' : value === false ? 'false' : null}
          disabled={disabled}
          ariaLabel={sub.label}
          onChange={(v) => onChange(v === 'true')}
        />
      );
    case 'rating':
      return (
        <RatingInput
          max={sub.rating?.max ?? 5}
          value={typeof value === 'number' ? value : 0}
          disabled={disabled}
          ariaLabel={sub.label}
          onChange={(v) => onChange(v)}
        />
      );
    case 'email':
    case 'url':
    case 'phone':
    case 'text':
    default:
      return (
        <Input
          {...common}
          type={sub.type === 'email' ? 'email' : sub.type === 'url' ? 'url' : sub.type === 'phone' ? 'tel' : 'text'}
          value={String(value ?? '')}
          placeholder={sub.placeholder}
          onChange={(e) => onChange(e.target.value)}
          className={cn(invalid && 'aria-invalid')}
        />
      );
  }
}
