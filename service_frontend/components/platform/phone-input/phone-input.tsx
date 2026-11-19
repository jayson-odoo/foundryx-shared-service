'use client';

import { useMemo, useState } from 'react';
import { ChevronDown } from 'lucide-react';
import {
  AsYouType,
  Metadata,
  getCountries,
  getCountryCallingCode,
  parsePhoneNumberFromString,
  type CountryCode,
} from 'libphonenumber-js';
import { cn } from '@/lib/utils';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';

/**
 * Phone field mirroring the Sorento CRM Dealer Access phone input
 * (`components/common/PhoneInput.tsx`, lane FEEDBACK-SHARE-SS-HOST, owner
 * 19 Nov): one bordered row of [flag + chevron country picker] [dial code]
 * [tel input]. Formats as you type, drops the trunk 0, a typed or pasted
 * international prefix switches the country, emits E.164. The error shows only
 * after blur (or when the caller forces it on submit), never while typing.
 */
export interface PhoneInputMeta {
  valid: boolean;
  country: CountryCode;
}

export interface PhoneInputProps {
  /** E.164 or ''. Read once on mount; the field owns its text afterwards. */
  value: string;
  onChange: (e164: string, meta: PhoneInputMeta) => void;
  defaultCountry?: CountryCode;
  id?: string;
  name?: string;
  disabled?: boolean;
  autoFocus?: boolean;
  /** Force the error (e.g. on submit). */
  showError?: boolean;
  errorMessage?: string;
  className?: string;
  'aria-label'?: string;
  onBlur?: () => void;
}

interface CountryRow {
  code: CountryCode;
  name: string;
  dial: string;
  flag: string;
}

const PLACEHOLDERS: Partial<Record<CountryCode, string>> = { MY: '12-345 6789' };

function flagOf(code: string): string {
  return String.fromCodePoint(...code.split('').map((c) => 0x1f1e6 + c.charCodeAt(0) - 65));
}

let cachedRows: CountryRow[] | null = null;

function countryRows(): CountryRow[] {
  if (cachedRows) return cachedRows;
  const names = new Intl.DisplayNames(['en'], { type: 'region' });
  cachedRows = getCountries()
    .map((code) => ({
      code,
      name: names.of(code) ?? code,
      dial: `+${getCountryCallingCode(code)}`,
      flag: flagOf(code),
    }))
    .sort((a, b) => a.name.localeCompare(b.name));
  return cachedRows;
}

function countryName(code: CountryCode): string {
  return countryRows().find((r) => r.code === code)?.name ?? code;
}

function trunkPrefix(country: CountryCode): string {
  const meta = new Metadata();
  meta.selectNumberingPlan(country);
  // `nationalPrefix()` exists at runtime but is missing from the typings.
  const plan = meta.numberingPlan as unknown as { nationalPrefix(): string | undefined } | undefined;
  return plan?.nationalPrefix() ?? '';
}

/** National display text for ``digits`` (no trunk 0), formatted for ``country``. */
function formatNational(country: CountryCode, digits: string): string {
  if (!digits) return '';
  const trunk = trunkPrefix(country);
  if (trunk === '0') {
    // Trunk-0 countries format as dialled at home: format WITH the 0, then
    // drop it again (shows "16-000 0509", never "016-...").
    const withTrunk = new AsYouType(country).input(`0${digits}`);
    if (withTrunk.startsWith('0')) return withTrunk.slice(1).replace(/^[\s-]+/, '');
  }
  return new AsYouType(country).input(digits);
}

function toE164(country: CountryCode, digits: string): string {
  return digits ? `+${getCountryCallingCode(country)}${digits}` : '';
}

function isValidE164(e164: string): boolean {
  return Boolean(e164 && parsePhoneNumberFromString(e164)?.isValid());
}

interface FieldState {
  country: CountryCode;
  digits: string;
  /** An international prefix still being typed (no country yet): shown as is. */
  raw?: string;
}

/** ``(country, national digits)`` for raw text typed or pasted in ``country``. */
function parseRaw(raw: string, country: CountryCode): FieldState {
  const trimmed = raw.trim();
  let digits = trimmed.replace(/\D/g, '');
  const international = trimmed.startsWith('+') || digits.startsWith('00');
  if (digits.startsWith('00')) digits = digits.slice(2);
  const calling = getCountryCallingCode(country);
  const ownPrefix = !international && digits.startsWith(calling) && isValidE164(`+${digits}`);
  if (international || ownPrefix) {
    const typer = new AsYouType();
    typer.input(`+${digits}`);
    const found = typer.getCountry();
    if (found) return { country: found, digits: typer.getNationalNumber() };
    if (!international) return { country, digits: digits.slice(calling.length) };
    return { country, digits: '', raw: digits ? `+${digits}` : trimmed ? '+' : '' };
  }
  if (digits.startsWith('0')) digits = digits.replace(/^0+/, '');
  return { country, digits };
}

function initialState(value: string, fallback: CountryCode): FieldState {
  const parsed = value ? parsePhoneNumberFromString(value) : undefined;
  if (parsed?.country) return { country: parsed.country, digits: parsed.nationalNumber };
  return { country: fallback, digits: '' };
}

export function PhoneInput({
  value,
  onChange,
  defaultCountry = 'MY',
  id,
  name,
  disabled = false,
  autoFocus = false,
  showError = false,
  errorMessage = 'Enter a complete phone number.',
  className,
  'aria-label': ariaLabel,
  onBlur,
}: PhoneInputProps) {
  const [state, setState] = useState(() => initialState(value, defaultCountry));
  const [touched, setTouched] = useState(false);
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const rows = useMemo(() => countryRows(), []);
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter(
      (r) => r.name.toLowerCase().includes(q) || r.code.toLowerCase() === q || r.dial.includes(q),
    );
  }, [rows, query]);
  const { country, digits, raw } = state;
  const dial = `+${getCountryCallingCode(country)}`;
  const e164 = toE164(country, digits);
  const valid = isValidE164(e164);
  const errorShown = !valid && (showError || (touched && digits.length > 0));
  const errorId = id ? `${id}-error` : undefined;

  const emit = (next: FieldState) => {
    setState(next);
    const out = toE164(next.country, next.digits);
    onChange(out, { valid: isValidE164(out), country: next.country });
  };

  return (
    <div className={cn('flex flex-col gap-1', className)}>
      <div
        className={cn(
          'flex h-10 items-center rounded-md border border-input bg-background shadow-xs shadow-black/5',
          'focus-within:ring-[3px] focus-within:ring-ring/30 focus-within:border-ring',
          errorShown && 'border-destructive',
          disabled && 'opacity-60',
        )}
      >
        <Popover
          open={open}
          onOpenChange={(o) => {
            setOpen(o);
            if (!o) setQuery('');
          }}
          modal
        >
          <PopoverTrigger asChild>
            <button
              type="button"
              disabled={disabled}
              aria-label={`Country: ${countryName(country)} (${dial})`}
              className="flex h-full shrink-0 items-center gap-1 rounded-s-md px-2.5 hover:bg-accent"
            >
              <span aria-hidden className="text-base leading-none">
                {flagOf(country)}
              </span>
              <ChevronDown aria-hidden className="size-3.5 opacity-50" />
            </button>
          </PopoverTrigger>
          <PopoverContent className="w-72 p-0" align="start">
            <Command shouldFilter={false}>
              <CommandInput placeholder="Search..." value={query} onValueChange={setQuery} />
              <CommandList className="max-h-64">
                <CommandEmpty>No results found.</CommandEmpty>
                <CommandGroup>
                  {shown.map((row) => (
                    <CommandItem
                      key={row.code}
                      value={`${row.name} ${row.code} ${row.dial}`}
                      onSelect={() => {
                        setOpen(false);
                        setQuery('');
                        emit({ country: row.code, digits });
                      }}
                    >
                      <span aria-hidden className="text-base leading-none">
                        {row.flag}
                      </span>
                      <span className="flex-1 truncate">{row.name}</span>
                      <span className="text-muted-foreground">{row.dial}</span>
                    </CommandItem>
                  ))}
                </CommandGroup>
              </CommandList>
            </Command>
          </PopoverContent>
        </Popover>
        <span className="shrink-0 ps-1 pe-2 text-sm text-muted-foreground">{dial}</span>
        <input
          id={id}
          name={name}
          type="tel"
          inputMode="tel"
          autoComplete="tel"
          autoFocus={autoFocus}
          disabled={disabled}
          aria-label={ariaLabel}
          aria-invalid={errorShown || undefined}
          aria-describedby={errorShown ? errorId : undefined}
          placeholder={PLACEHOLDERS[country] ?? ''}
          value={raw ?? formatNational(country, digits)}
          onChange={(e) => emit(parseRaw(e.target.value, country))}
          onBlur={() => {
            setTouched(true);
            onBlur?.();
          }}
          className="h-full min-w-0 flex-1 rounded-e-md bg-transparent pe-3 text-sm outline-none placeholder:text-muted-foreground"
        />
      </div>
      {errorShown && (
        <p id={errorId} role="alert" className="text-xs text-destructive">
          {errorMessage}
        </p>
      )}
    </div>
  );
}
