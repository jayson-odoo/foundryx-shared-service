'use client';

/**
 * Structured cron builder (plan sprint-2/09 D9) - frequency + sub-fields
 * compile to a standard 5-field cron string (lib/cron.ts), with an IANA
 * timezone. No raw-cron input on purpose: a mistyped expression is a silent
 * footgun, so the schedule is only ever expressible through the builder. The
 * schedule trigger stores `cron` (string) + `timezone` (IANA, '' = tenant tz).
 *
 * Mount-initialized from the incoming cron - bump the parent `key` (node id) to
 * reload it for a different node.
 */
import { useEffect, useMemo, useState } from 'react';
import { getTimeZones } from '@/i18n/timezones';
import { Input } from '@/components/ui/input';
import { SearchSelect } from '@/components/platform/search-select';
import {
  compileCron,
  describeCron,
  parseCron,
  DEFAULT_CRON_STATE,
  WEEKDAYS,
  type CronFrequency,
  type CronState,
} from '@/lib/cron';

const BROWSER_DEFAULT = '__tenant__';

const FREQUENCIES: { value: CronFrequency; label: string }[] = [
  { value: 'minute', label: 'Every minute' },
  { value: 'hour', label: 'Hourly' },
  { value: 'day', label: 'Daily' },
  { value: 'week', label: 'Weekly' },
  { value: 'month', label: 'Monthly' },
];

export interface CronBuilderProps {
  cron: string;
  timezone: string;
  disabled?: boolean;
  onChange: (cron: string, timezone: string) => void;
}

export function CronBuilder({ cron, timezone, disabled = false, onChange }: CronBuilderProps) {
  const [state, setState] = useState<CronState>(() => parseCron(cron) ?? DEFAULT_CRON_STATE);

  // Reconcile when the cron prop changes externally (undo/redo, Cancel/discard)
  // without a remount - otherwise the sub-field inputs show a stale schedule and
  // the next edit recompiles the stale state, clobbering the change.
  useEffect(() => {
    const parsed = parseCron(cron);
    if (parsed && compileCron(parsed) !== compileCron(state)) setState(parsed);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cron]);

  const tzOptions = useMemo(
    () => [{ value: BROWSER_DEFAULT, label: 'Tenant default timezone' }, ...getTimeZones()],
    [],
  );

  const emit = (next: CronState) => {
    setState(next);
    onChange(compileCron(next), timezone);
  };
  const patch = (p: Partial<CronState>) => emit({ ...state, ...p });

  const timeValue = `${String(state.hour).padStart(2, '0')}:${String(state.minute).padStart(2, '0')}`;
  const onTime = (v: string) => {
    const [h, m] = v.split(':').map((s) => Number(s));
    patch({ hour: Number.isNaN(h) ? 0 : h, minute: Number.isNaN(m) ? 0 : m });
  };

  return (
    <div className="flex flex-col gap-2.5" data-testid="cron-builder">
      <SearchSelect
        options={FREQUENCIES}
        value={state.frequency}
        onChange={(v) => patch({ frequency: v as CronFrequency })}
        ariaLabel="Frequency"
        disabled={disabled}
      />

      {state.frequency === 'minute' && (
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">Every</span>
          <Input
            type="number"
            min={1}
            max={59}
            className="h-8 w-20"
            value={state.interval}
            disabled={disabled}
            aria-label="Minute interval"
            onChange={(e) => patch({ interval: Number(e.target.value) || 1 })}
          />
          <span className="text-xs text-muted-foreground">minute(s)</span>
        </div>
      )}

      {state.frequency === 'hour' && (
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">At minute</span>
          <Input
            type="number"
            min={0}
            max={59}
            className="h-8 w-20"
            value={state.minute}
            disabled={disabled}
            aria-label="Minute of hour"
            onChange={(e) => patch({ minute: Number(e.target.value) || 0 })}
          />
        </div>
      )}

      {state.frequency === 'week' && (
        <SearchSelect
          options={WEEKDAYS.map((d) => ({ value: String(d.value), label: d.label }))}
          value={String(state.dayOfWeek)}
          onChange={(v) => patch({ dayOfWeek: Number(v) })}
          ariaLabel="Day of week"
          disabled={disabled}
        />
      )}

      {state.frequency === 'month' && (
        <SearchSelect
          options={Array.from({ length: 31 }, (_, i) => ({ value: String(i + 1), label: `Day ${i + 1}` }))}
          value={String(state.dayOfMonth)}
          onChange={(v) => patch({ dayOfMonth: Number(v) })}
          ariaLabel="Day of month"
          disabled={disabled}
        />
      )}

      {(state.frequency === 'day' || state.frequency === 'week' || state.frequency === 'month') && (
        <div className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground">At</span>
          <Input
            type="time"
            className="h-8 w-32"
            value={timeValue}
            disabled={disabled}
            aria-label="Time of day"
            onChange={(e) => onTime(e.target.value)}
          />
        </div>
      )}

      <SearchSelect
        options={tzOptions}
        value={timezone === '' ? BROWSER_DEFAULT : timezone}
        onChange={(v) => onChange(cron, v === BROWSER_DEFAULT ? '' : v)}
        ariaLabel="Timezone"
        searchPlaceholder="Search timezones…"
        disabled={disabled}
      />

      <p className="text-xs text-muted-foreground" data-testid="cron-summary">
        {describeCron(cron || '')} · <code className="text-2xs">{cron || '-'}</code>
      </p>
    </div>
  );
}
