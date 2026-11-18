'use client';

/**
 * The Foundryx UIUX money field (playbook 0.71.0 "Money fields", gap audit
 * "Money in more than one currency"): the currency sits inside the field
 * ("RM" for the home currency, the ISO code for any other), the amount is
 * right-aligned in tabular figures, typed as "14000" or "14,000" and tidied to
 * "14,000.00" when you leave the field. Phones open the decimal keypad. A
 * wrong amount gets a short message right under the field. Where the record's
 * currency can change, the currency is a small searchable dropdown.
 *
 * New for page waves: pages opt in by using it under `useFx()`.
 */
import { useEffect, useId, useState } from 'react';
import { cn } from '@/lib/utils';
import {
  formatFxAmount,
  fxCurrencyDecimals,
  fxCurrencyLabel,
  parseMoneyInput,
} from '@/lib/money';
import { FX_FIELD_BOX, FX_FIELD_INNER, FX_FIELD_SIZE, type FxFieldSize } from './classes';
import { FxFieldMessage } from './fx-input';
import { FxSearchSelect } from './fx-search-select';

export const FX_MONEY_HINT = 'Enter an amount, like 14,000.00';

export interface FxMoneyFieldProps {
  value: number | null;
  onChange: (value: number | null) => void;
  /** ISO code ("MYR", "SGD"); the home currency when omitted. */
  currency?: string | null;
  /** When the record's currency can change: the codes to pick from. */
  currencies?: readonly string[];
  onCurrencyChange?: (currency: string) => void;
  /** Decimal places; default the currency's own (JPY none, most two). */
  decimals?: number;
  allowNegative?: boolean;
  disabled?: boolean;
  placeholder?: string;
  size?: FxFieldSize;
  id?: string;
  'aria-label'?: string;
  'aria-labelledby'?: string;
  className?: string;
  /** A message from the form (it wins over the field's own). */
  error?: string | null;
}

export function FxMoneyField({
  value,
  onChange,
  currency,
  currencies,
  onCurrencyChange,
  decimals,
  allowNegative = false,
  disabled,
  placeholder,
  size = 'md',
  id,
  className,
  error,
  ...aria
}: FxMoneyFieldProps) {
  const places = decimals ?? fxCurrencyDecimals(currency);
  const tidy = (n: number | null) => (n === null ? '' : formatFxAmount(n, places));
  const [text, setText] = useState(tidy(value));
  const [message, setMessage] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const messageId = useId();

  useEffect(() => {
    if (!editing) setText(tidy(value));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- re-tidy when the value or decimals change outside typing
  }, [value, places]);

  const commit = () => {
    setEditing(false);
    if (!text.trim()) {
      setMessage(null);
      if (value !== null) onChange(null);
      return;
    }
    const parsed = parseMoneyInput(text);
    if (parsed === null || (!allowNegative && parsed < 0)) {
      setMessage(FX_MONEY_HINT);
      return;
    }
    const rounded = Number(parsed.toFixed(places));
    setMessage(null);
    setText(formatFxAmount(rounded, places));
    if (rounded !== value) onChange(rounded);
  };

  const shown = error ?? message;
  const label = fxCurrencyLabel(currency);

  return (
    <div className={cn('relative', className)}>
      <div className={cn(FX_FIELD_BOX, FX_FIELD_SIZE[size], 'gap-2', currencies && 'ps-1')} data-fx-field="">
        {currencies && onCurrencyChange ? (
          <FxSearchSelect
            ariaLabel="Currency"
            value={(currency ?? '').toUpperCase() || 'MYR'}
            onChange={onCurrencyChange}
            disabled={disabled}
            options={currencies.map((code) => ({
              value: code,
              label: fxCurrencyLabel(code),
              description: fxCurrencyLabel(code) === code ? undefined : code,
            }))}
            className="h-[calc(100%-6px)] w-auto shrink-0 gap-1 rounded-(--fx-r-s) border-0 bg-(--fx-surface-2) px-2 text-(--fx-ink-2) shadow-none enabled:hover:translate-y-0 enabled:hover:shadow-none"
          />
        ) : (
          <span className="shrink-0 text-(--fx-ink-3)" aria-hidden="true">
            {label}
          </span>
        )}
        <input
          id={id}
          type="text"
          inputMode="decimal"
          autoComplete="off"
          value={text}
          disabled={disabled}
          placeholder={placeholder}
          aria-invalid={shown ? true : undefined}
          aria-describedby={shown ? messageId : undefined}
          aria-label={aria['aria-label'] ? `${aria['aria-label']} (${label})` : undefined}
          aria-labelledby={aria['aria-labelledby']}
          onChange={(e) => {
            setEditing(true);
            setText(e.target.value);
          }}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === 'Enter') commit();
          }}
          className={cn(FX_FIELD_INNER, 'h-full text-end tabular-nums')}
        />
      </div>
      <FxFieldMessage id={messageId}>{shown}</FxFieldMessage>
    </div>
  );
}
