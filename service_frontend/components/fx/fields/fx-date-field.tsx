'use client';

/**
 * The Foundryx UIUX date field (playbook 0.71.0 "Date fields"): it looks
 * like every other field with a small calendar icon on the right. You can
 * type the date ("14/11/2026", "14 Nov", "tomorrow"); it is tidied to
 * "14 Nov 2026" when you leave the field, and a date it can't read gets a
 * short message under the field. The icon or the field's button opens the
 * month calendar. The value is a calendar day ("2026-11-14"), so it never
 * shifts with the time zone.
 *
 * New for page waves: pages opt in by using it under `useFx()`.
 */
import { useEffect, useId, useState } from 'react';
import { CalendarIcon } from 'lucide-react';
import { cn } from '@/lib/utils';
import { dateKey, formatFxDayKey } from '@/lib/datetime';
import { parseTypedDate } from '@/lib/fx/fields';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { parseKey, localDateKey } from '@/components/platform/date-range-picker/date-range-picker';
import { FX_FIELD_BOX, FX_FIELD_INNER, FX_FIELD_SIZE, FX_MENU, type FxFieldSize } from './classes';
import { FxCalendar } from './fx-calendar';
import { FxFieldMessage } from './fx-input';
import { FxFieldContext, fxControlName, useFxFieldIds } from './fx-field-context';

export const FX_DATE_HINT = 'Enter a date, like 14 Nov 2026';

export interface FxDateFieldProps {
  /** The chosen calendar day ("2026-11-14"), or null. */
  value: string | null;
  onChange: (value: string | null) => void;
  /** The zone "today" and "tomorrow" count in (default the browser's). */
  timeZone?: string | null;
  /** Inclusive bounds ("2026-11-01"); days outside can't be picked or typed. */
  minDate?: string;
  maxDate?: string;
  disabled?: boolean;
  placeholder?: string;
  size?: FxFieldSize;
  id?: string;
  'aria-label'?: string;
  'aria-labelledby'?: string;
  className?: string;
  /** Today's key, for tests; default the real today in `timeZone`. */
  today?: string;
}

function outOfRange(key: string, min?: string, max?: string): string | null {
  if (min && key < min) return max ? `Pick a day from ${formatFxDayKey(min)} to ${formatFxDayKey(max)}` : `Pick a day from ${formatFxDayKey(min)}`;
  if (max && key > max) return min ? `Pick a day from ${formatFxDayKey(min)} to ${formatFxDayKey(max)}` : `Pick a day up to ${formatFxDayKey(max)}`;
  return null;
}

export function FxDateField({
  value,
  onChange,
  timeZone,
  minDate,
  maxDate,
  disabled,
  placeholder,
  size = 'md',
  id,
  className,
  today,
  ...aria
}: FxDateFieldProps) {
  const [text, setText] = useState(value ? formatFxDayKey(value) : '');
  const [message, setMessage] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const messageId = useId();
  // Inside a labelled FxField the input takes the field's id and label.
  const field = useFxFieldIds();
  const naming = field
    ? fxControlName(
        {
          id,
          ariaLabel: aria['aria-label'],
          ariaLabelledBy: aria['aria-labelledby'],
          ariaDescribedBy: message ? messageId : undefined,
        },
        field,
      )
    : null;

  useEffect(() => {
    setText(value ? formatFxDayKey(value) : '');
    setMessage(null);
  }, [value]);

  const todayKey = () => today ?? dateKey(new Date(), { timeZone }) ?? new Date().toISOString().slice(0, 10);

  const commit = () => {
    if (!text.trim()) {
      setMessage(null);
      if (value !== null) onChange(null);
      return;
    }
    const key = parseTypedDate(text, todayKey());
    if (!key) {
      setMessage(FX_DATE_HINT);
      return;
    }
    const range = outOfRange(key, minDate, maxDate);
    if (range) {
      setMessage(range);
      return;
    }
    setMessage(null);
    setText(formatFxDayKey(key));
    if (key !== value) onChange(key);
  };

  return (
    <div className={cn('relative', className)}>
      <div className={cn(FX_FIELD_BOX, FX_FIELD_SIZE[size], 'gap-2 pe-1')} data-fx-field="">
        <input
          id={id}
          type="text"
          inputMode="text"
          autoComplete="off"
          value={text}
          disabled={disabled}
          placeholder={placeholder}
          aria-invalid={message ? true : undefined}
          aria-describedby={message ? messageId : undefined}
          {...aria}
          {...naming}
          onChange={(e) => setText(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              commit();
            }
          }}
          className={cn(FX_FIELD_INNER, 'h-full tabular-nums')}
        />
        <Popover open={open} onOpenChange={setOpen}>
          <PopoverTrigger asChild>
            <button
              type="button"
              disabled={disabled}
              aria-label="Open calendar"
              className={cn(
                PRESSED_CLASS,
                'inline-flex size-7 shrink-0 items-center justify-center rounded-(--fx-r-s) text-(--fx-ink-3) hover:bg-(--fx-surface-2) hover:text-(--fx-ink) disabled:pointer-events-none',
              )}
            >
              <CalendarIcon className="size-4" aria-hidden="true" />
            </button>
          </PopoverTrigger>
          <PopoverContent className={cn(FX_MENU, 'w-auto p-0')} align="end">
            <FxFieldContext.Provider value={null}>
            <FxCalendar
              mode="single"
              selected={value ? parseKey(value) : undefined}
              defaultMonth={value ? parseKey(value) : undefined}
              disabled={[
                ...(minDate ? [{ before: parseKey(minDate) }] : []),
                ...(maxDate ? [{ after: parseKey(maxDate) }] : []),
              ]}
              onSelect={(day) => {
                if (!day) return;
                const key = localDateKey(day);
                setMessage(null);
                setText(formatFxDayKey(key));
                onChange(key);
                setOpen(false);
              }}
            />
            </FxFieldContext.Provider>
          </PopoverContent>
        </Popover>
      </div>
      <FxFieldMessage id={messageId}>{message}</FxFieldMessage>
    </div>
  );
}
