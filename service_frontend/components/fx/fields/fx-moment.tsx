'use client';

/**
 * Moments the Foundryx UIUX way (playbook-uiux.md, gap audit "Times and time
 * zones"). `FxMoment` reads relative in lists and feeds ("5 min", "Yesterday")
 * with the full "14 Nov 2026, 2:14 pm" as its tooltip; `FxDayLine` is the
 * line between days in a long feed; `FxZoneLine` sits under a time picker
 * ("Kuala Lumpur time (GMT+8)"). All read the viewer's zone through
 * `useDatetime()`.
 */
import { cn } from '@/lib/utils';
import { formatFxDateTime, formatFxZoneLine } from '@/lib/datetime';
import { useDatetime } from '@/hooks/use-datetime';

export function FxMoment({ iso, className }: { iso: string | null | undefined; className?: string }) {
  const { formatRelative, timeZone } = useDatetime();
  if (!iso) return <span className={className}>-</span>;
  return (
    <time dateTime={iso} title={formatFxDateTime(iso, { timeZone })} className={cn('tabular-nums', className)}>
      {formatRelative(iso)}
    </time>
  );
}

export function FxDayLine({ iso, className }: { iso: string; className?: string }) {
  const { formatDayLine } = useDatetime();
  return (
    <div role="separator" className={cn('flex items-center gap-3 py-2 text-xs font-semibold text-(--fx-ink-3)', className)}>
      <span className="h-px flex-1 bg-(--fx-line)" aria-hidden="true" />
      {formatDayLine(iso)}
      <span className="h-px flex-1 bg-(--fx-line)" aria-hidden="true" />
    </div>
  );
}

/** The zone a picked time is in; `timeZone` overrides the viewer's (a report's own zone). */
export function FxZoneLine({ timeZone, className }: { timeZone?: string; className?: string }) {
  const { zoneLine } = useDatetime();
  return (
    <p data-fx-zone-line="" className={cn('text-xs text-(--fx-ink-3)', className)}>
      {timeZone ? formatFxZoneLine(timeZone) : zoneLine}
    </p>
  );
}
