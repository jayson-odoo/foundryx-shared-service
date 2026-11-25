'use client';

/**
 * Typed From / To fields for the shared range picker (SS-BACKFILL-DATE-FLOOR).
 *
 * Paging a month calendar back to 2010 is not a real option, so both range
 * pickers carry two text fields above the calendar: type "05/11/2026" (or
 * "2026-11-05", "5 Nov 2026") and leave the field or press Enter. A day the
 * picker would disable (before `minDate` / after `maxDate`) is refused with a
 * short message, exactly as the calendar would refuse the click. A From after
 * the current To (or a To before From) moves the other end with it, so the
 * range is never upside down. Each accepted day also jumps the calendar to
 * its month (`onJump`).
 */
import { useEffect, useId, useState } from 'react';
import { formatDmyDate } from '@/lib/datetime';
import { parseTypedDate } from '@/lib/fx/fields';
import { cn } from '@/lib/utils';

export interface DateRangeTypedInputsProps {
  from: string;
  to: string;
  /** Inclusive bounds (`YYYY-MM-DD`), the same ones the calendar disables by. */
  minDate?: string;
  maxDate?: string;
  /** Today's key, used for "today" / day-month-only input. */
  today: string;
  onChange: (from: string, to: string) => void;
  /** Called with the accepted day so the calendar can show its month. */
  onJump?: (day: string) => void;
  className?: string;
}

type End = 'from' | 'to';

const show = (day: string) => (day ? formatDmyDate(day) : '');

export function rangeBoundsMessage(
  day: string,
  minDate?: string,
  maxDate?: string,
): string | null {
  if ((minDate && day < minDate) || (maxDate && day > maxDate)) {
    if (minDate && maxDate)
      return `Pick a day from ${formatDmyDate(minDate)} to ${formatDmyDate(maxDate)}`;
    if (minDate) return `Pick a day from ${formatDmyDate(minDate)}`;
    return `Pick a day up to ${formatDmyDate(maxDate as string)}`;
  }
  return null;
}

export function DateRangeTypedInputs({
  from,
  to,
  minDate,
  maxDate,
  today,
  onChange,
  onJump,
  className,
}: DateRangeTypedInputsProps) {
  const [text, setText] = useState<Record<End, string>>({
    from: show(from),
    to: show(to),
  });
  const [message, setMessage] = useState<string | null>(null);
  const messageId = useId();

  useEffect(() => {
    setText({ from: show(from), to: show(to) });
  }, [from, to]);

  const commit = (end: End) => {
    const typed = text[end].trim();
    const current = end === 'from' ? from : to;
    if (!typed) {
      setText((t) => ({ ...t, [end]: show(current) }));
      setMessage(null);
      return;
    }
    const day = parseTypedDate(typed, today);
    if (!day) {
      setMessage('Enter a date like 05/11/2026');
      return;
    }
    const bounds = rangeBoundsMessage(day, minDate, maxDate);
    if (bounds) {
      setMessage(bounds);
      return;
    }
    setMessage(null);
    setText((t) => ({ ...t, [end]: show(day) }));
    onJump?.(day);
    if (day === current) return;
    if (end === 'from') onChange(day, !to || to < day ? day : to);
    else onChange(!from || from > day ? day : from, day);
  };

  const field = (end: End, label: string) => (
    <label className="flex min-w-0 flex-1 flex-col gap-1 text-xs text-muted-foreground">
      {label}
      <input
        type="text"
        inputMode="numeric"
        autoComplete="off"
        placeholder="dd/mm/yyyy"
        aria-label={label}
        aria-invalid={message ? true : undefined}
        aria-describedby={message ? messageId : undefined}
        data-testid={`date-range-typed-${end}`}
        value={text[end]}
        onChange={(e) => setText((t) => ({ ...t, [end]: e.target.value }))}
        onBlur={() => commit(end)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            commit(end);
          }
        }}
        className="h-8 w-full min-w-0 rounded-md border border-input bg-background px-2 text-sm tabular-nums text-foreground outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
      />
    </label>
  );

  return (
    <div
      className={cn(
        'flex flex-col gap-1 border-b border-border p-3',
        className,
      )}
    >
      <div className="flex gap-2">
        {field('from', 'From')}
        {field('to', 'To')}
      </div>
      {message && (
        <p id={messageId} role="alert" className="text-xs text-destructive">
          {message}
        </p>
      )}
    </div>
  );
}
