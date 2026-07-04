'use client';

/**
 * Address composite (plan sprint-3/01) — line1/line2/city/state/postcode text
 * inputs + a searchable country select (the only dropdown primitive, house
 * mandate). The answer is a `FormAddressAnswer`; sub-keys are written immutably
 * so the parent re-renders cleanly. Whole composite collapses to one column
 * under `md:` for mobile.
 */
import { SearchSelect } from '@/components/platform/search-select';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { COUNTRIES } from './countries';
import type { FormAddressAnswer } from '@/types/forms';

export interface AddressFieldProps {
  value: FormAddressAnswer;
  onChange: (value: FormAddressAnswer) => void;
  disabled?: boolean;
  invalid?: boolean;
  idBase: string;
}

const COUNTRY_OPTIONS = COUNTRIES.map((c) => ({ value: c.code, label: c.name }));

export function AddressField({ value, onChange, disabled, invalid, idBase }: AddressFieldProps) {
  const set = (patch: Partial<FormAddressAnswer>) => onChange({ ...value, ...patch });

  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
      <div className="space-y-1 md:col-span-2">
        <Label htmlFor={`${idBase}-line1`} variant="secondary">Address line 1</Label>
        <Input
          id={`${idBase}-line1`}
          value={value.line1 ?? ''}
          disabled={disabled}
          aria-invalid={invalid || undefined}
          onChange={(e) => set({ line1: e.target.value })}
        />
      </div>
      <div className="space-y-1 md:col-span-2">
        <Label htmlFor={`${idBase}-line2`} variant="secondary">Address line 2</Label>
        <Input
          id={`${idBase}-line2`}
          value={value.line2 ?? ''}
          disabled={disabled}
          onChange={(e) => set({ line2: e.target.value })}
        />
      </div>
      <div className="space-y-1">
        <Label htmlFor={`${idBase}-city`} variant="secondary">City</Label>
        <Input
          id={`${idBase}-city`}
          value={value.city ?? ''}
          disabled={disabled}
          aria-invalid={invalid || undefined}
          onChange={(e) => set({ city: e.target.value })}
        />
      </div>
      <div className="space-y-1">
        <Label htmlFor={`${idBase}-state`} variant="secondary">State / Province</Label>
        <Input
          id={`${idBase}-state`}
          value={value.state ?? ''}
          disabled={disabled}
          onChange={(e) => set({ state: e.target.value })}
        />
      </div>
      <div className="space-y-1">
        <Label htmlFor={`${idBase}-postcode`} variant="secondary">Postcode</Label>
        <Input
          id={`${idBase}-postcode`}
          value={value.postcode ?? ''}
          disabled={disabled}
          onChange={(e) => set({ postcode: e.target.value })}
        />
      </div>
      <div className="space-y-1">
        <Label variant="secondary">Country</Label>
        <SearchSelect
          options={COUNTRY_OPTIONS}
          value={value.country ?? null}
          disabled={disabled}
          ariaLabel="Country"
          placeholder="Select a country…"
          onChange={(code) => set({ country: code })}
        />
      </div>
    </div>
  );
}
