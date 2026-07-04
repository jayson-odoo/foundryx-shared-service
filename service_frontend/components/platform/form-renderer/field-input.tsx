'use client';

/**
 * Per-type fill input dispatcher (plan sprint-3/01, D7) — maps a `FormField`
 * to its interactive control. Dropdowns use the house SearchSelect/MultiSelect
 * primitives ONLY. Computed fields are read-only (recomputed live). Every
 * control receives only the doc's own labels/placeholders/helpText — NO
 * instructional copy (foolproof-UI mandate).
 */
import { MultiSelect } from '@/components/platform/multi-select';
import { SearchSelect } from '@/components/platform/search-select';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Textarea } from '@/components/ui/textarea';
import { cn } from '@/lib/utils';
import type {
  FormAddressAnswer,
  FormAnswerValue,
  FormField,
  FormFieldErrors,
  FormFileAnswer,
} from '@/types/forms';
import { AddressField } from './address-field';
import { FileInput } from './file-input';
import { RatingInput } from './rating-input';
import { RepeaterField } from './repeater-field';
import { TableField } from './table-field';
import { SignaturePad } from './signature-pad';

export interface FieldInputProps {
  field: FormField;
  value: FormAnswerValue | undefined;
  onChange: (value: FormAnswerValue) => void;
  /** All errors — composite types read their nested `key.row.subKey` entries. */
  errors: FormFieldErrors;
  invalid?: boolean;
  /** Computed display value (only for `computed` fields). */
  computed?: number | null;
  id: string;
  disabled?: boolean;
}

export function FieldInput({
  field,
  value,
  onChange,
  errors,
  invalid,
  computed,
  id,
  disabled,
}: FieldInputProps) {
  const choiceOptions = (field.options?.items ?? []).map((o) => ({ value: o.value, label: o.label }));

  switch (field.type) {
    case 'textarea':
      return (
        <Textarea
          id={id}
          value={String(value ?? '')}
          placeholder={field.placeholder}
          disabled={disabled}
          aria-invalid={invalid || undefined}
          onChange={(e) => onChange(e.target.value)}
        />
      );

    case 'number':
    case 'integer': {
      const isInt = field.type === 'integer' || field.number?.integer;
      return (
        <Input
          id={id}
          type="number"
          inputMode={isInt ? 'numeric' : 'decimal'}
          value={value === null || value === undefined ? '' : String(value)}
          placeholder={field.placeholder}
          min={field.number?.min}
          max={field.number?.max}
          step={
            isInt
              ? '1'
              : field.number?.step ??
                (field.number?.decimals != null && field.number.decimals >= 0
                  ? String(10 ** -field.number.decimals)
                  : undefined)
          }
          disabled={disabled}
          aria-invalid={invalid || undefined}
          // Integer: block the keys that would introduce a fraction.
          onKeyDown={(e) => {
            if (isInt && ['.', ',', 'e', 'E'].includes(e.key)) e.preventDefault();
          }}
          onChange={(e) => onChange(e.target.value === '' ? '' : Number(e.target.value))}
          onBlur={(e) => {
            // Decimal mode: pad to exactly N places on blur (1 → 1.0000).
            const dp = field.number?.decimals;
            if (isInt || dp == null || dp < 0 || e.target.value === '') return;
            const n = Number(e.target.value);
            if (Number.isFinite(n)) onChange(n.toFixed(dp));
          }}
        />
      );
    }

    case 'select':
      return (
        <SearchSelect
          options={choiceOptions}
          value={value == null ? null : String(value)}
          placeholder={field.placeholder}
          disabled={disabled}
          ariaLabel={field.label}
          onChange={(v) => onChange(v)}
        />
      );

    case 'multiselect':
      return (
        <MultiSelect
          options={choiceOptions}
          value={Array.isArray(value) ? (value as string[]) : []}
          placeholder={field.placeholder}
          disabled={disabled}
          onChange={(v) => onChange(v)}
        />
      );

    case 'radio':
      return (
        <RadioGroup
          value={value == null ? '' : String(value)}
          disabled={disabled}
          aria-invalid={invalid || undefined}
          onValueChange={(v) => onChange(v)}
        >
          {choiceOptions.map((o) => (
            <label key={o.value} className="flex items-center gap-2 text-sm">
              <RadioGroupItem value={o.value} id={`${id}-${o.value}`} />
              {o.label}
            </label>
          ))}
        </RadioGroup>
      );

    case 'checkboxes': {
      const selected = Array.isArray(value) ? (value as string[]) : [];
      const toggle = (optionValue: string, checked: boolean) =>
        onChange(checked ? [...selected, optionValue] : selected.filter((v) => v !== optionValue));
      return (
        <div className="space-y-2.5">
          {choiceOptions.map((o) => (
            <label key={o.value} className="flex items-center gap-2 text-sm">
              <Checkbox
                checked={selected.includes(o.value)}
                disabled={disabled}
                onCheckedChange={(c) => toggle(o.value, c === true)}
              />
              {o.label}
            </label>
          ))}
        </div>
      );
    }

    case 'yesno': {
      const yes = value === true;
      const no = value === false;
      return (
        <div className="inline-flex gap-2" role="group" aria-label={field.label}>
          <Button
            type="button"
            variant={yes ? 'primary' : 'outline'}
            size="sm"
            disabled={disabled}
            aria-pressed={yes}
            onClick={() => onChange(true)}
          >
            Yes
          </Button>
          <Button
            type="button"
            variant={no ? 'primary' : 'outline'}
            size="sm"
            disabled={disabled}
            aria-pressed={no}
            onClick={() => onChange(false)}
          >
            No
          </Button>
        </div>
      );
    }

    case 'date':
      return (
        <Input
          id={id}
          type="date"
          value={String(value ?? '')}
          disabled={disabled}
          aria-invalid={invalid || undefined}
          onChange={(e) => onChange(e.target.value)}
        />
      );

    case 'datetime':
      return (
        <Input
          id={id}
          type="datetime-local"
          value={String(value ?? '')}
          disabled={disabled}
          aria-invalid={invalid || undefined}
          onChange={(e) => onChange(e.target.value)}
        />
      );

    case 'rating':
      return (
        <RatingInput
          max={field.rating?.max ?? 5}
          value={typeof value === 'number' ? value : 0}
          disabled={disabled}
          ariaLabel={field.label}
          onChange={(v) => onChange(v)}
        />
      );

    case 'file':
      return (
        <FileInput
          id={id}
          value={Array.isArray(value) && isFileList(value) ? value : []}
          config={field.file}
          disabled={disabled}
          invalid={invalid}
          onChange={(v) => onChange(v)}
        />
      );

    case 'signature':
      return (
        <SignaturePad
          value={typeof value === 'string' ? value : ''}
          disabled={disabled}
          invalid={invalid}
          ariaLabel={field.label}
          onChange={(v) => onChange(v)}
        />
      );

    case 'address':
      return (
        <AddressField
          idBase={id}
          value={isAddress(value) ? value : {}}
          disabled={disabled}
          invalid={invalid}
          onChange={(v) => onChange(v)}
        />
      );

    case 'repeater':
      return (
        <RepeaterField
          idBase={id}
          fieldKey={field.key ?? ''}
          subFields={field.repeater?.fields ?? []}
          minRows={field.repeater?.minRows}
          maxRows={field.repeater?.maxRows}
          value={Array.isArray(value) ? (value as Record<string, never>[]) : []}
          errors={errors}
          disabled={disabled}
          onChange={(v) => onChange(v)}
        />
      );

    case 'table':
      return (
        <TableField
          idBase={id}
          fieldKey={field.key ?? ''}
          columns={field.table?.columns ?? []}
          showRowNumbers={field.table?.showRowNumbers}
          minRows={field.table?.minRows}
          maxRows={field.table?.maxRows}
          value={Array.isArray(value) ? (value as Record<string, never>[]) : []}
          errors={errors}
          disabled={disabled}
          onChange={(v) => onChange(v)}
        />
      );

    case 'computed':
      return (
        <div
          id={id}
          data-slot="computed-value"
          className="flex h-9 items-center rounded-md border border-input bg-muted/50 px-3 text-sm text-foreground"
        >
          {computed === null || computed === undefined ? '—' : computed}
        </div>
      );

    case 'text':
    case 'email':
    case 'phone':
    case 'url':
    default:
      return (
        <Input
          id={id}
          type={field.type === 'email' ? 'email' : field.type === 'url' ? 'url' : field.type === 'phone' ? 'tel' : 'text'}
          value={String(value ?? '')}
          placeholder={field.placeholder}
          disabled={disabled}
          aria-invalid={invalid || undefined}
          onChange={(e) => onChange(e.target.value)}
          className={cn()}
        />
      );
  }
}

function isAddress(value: FormAnswerValue | undefined): value is FormAddressAnswer {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

function isFileList(value: unknown[]): value is FormFileAnswer[] {
  return value.every((v) => !!v && typeof v === 'object' && 'key' in v);
}
