'use client';

/**
 * My Account's time zone with the Foundryx UIUX switch on (slice W4-ACCOUNT).
 * The same searchable list of zones and the same save as with the switch off
 * (picking saves at once); what changes is how it reads:
 * - a labelled "Time zone" field with the zone line under it
 *   ("Kuala Lumpur time (GMT+8)"), no explanatory sentence;
 * - a done toast naming the zone, whose Undo saves the earlier choice back
 *   through the same request;
 * - a failed save shows under the field in the zone line's place, not as a
 *   toast.
 */
import { useMemo } from 'react';
import { toast } from '@/lib/toast';
import { getTimeZones } from '@/i18n/timezones';
import { SearchSelect } from '@/components/platform/search-select/search-select';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { FxField, FxZoneLine } from '@/components/fx/fields';
import { useTimezonePreference } from '@/hooks/use-timezone-preference';

/** Sentinel option (the same as the switch-off card's): back to the device's zone. */
const BROWSER_DEFAULT = '__browser__';

/** "Kuala Lumpur" from "Asia/Kuala_Lumpur" (pure, tested). */
export function fxZoneCity(timeZone: string): string {
  if (timeZone === 'UTC' || timeZone === 'Etc/UTC') return 'UTC';
  return (timeZone.split('/').pop() ?? timeZone).replace(/_/g, ' ');
}

export function FxTimezoneCard() {
  const { timezone, browserTimeZone, isSaving, error, save } = useTimezonePreference();

  // ~400 Intl formatter constructions - compute once.
  const options = useMemo(
    () => [
      {
        value: BROWSER_DEFAULT,
        label: `This device's zone (${browserTimeZone.replace(/_/g, ' ')})`,
      },
      ...getTimeZones(),
    ],
    [browserTimeZone],
  );

  const choose = async (next: string | null, previous: string | null, withUndo: boolean) => {
    const ok = await save(next);
    if (!ok) return;
    toast.fxDone({
      what: next ? `Time zone set to ${fxZoneCity(next)}` : "Time zone set to this device's zone",
      undo: withUndo ? () => void choose(previous, next, false) : undefined,
    });
  };

  const onChange = (value: string) => {
    const next = value === BROWSER_DEFAULT ? null : value;
    if (next === timezone) return;
    void choose(next, timezone, true);
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Preferences</CardTitle>
      </CardHeader>
      <CardContent>
        <FxField label="Time zone" className="max-w-md">
          <SearchSelect
            options={options}
            value={timezone ?? BROWSER_DEFAULT}
            onChange={onChange}
            disabled={isSaving}
            placeholder="Pick a time zone"
            searchPlaceholder="Search time zones"
            ariaLabel="Time zone"
          />
        </FxField>
        {/* The zone line's place holds the error, so nothing moves. */}
        {error ? (
          <p role="alert" data-fx-message="error" className="mt-1 text-xs text-(--fx-act)">
            Couldn&apos;t save the time zone. Try again.
          </p>
        ) : (
          <FxZoneLine timeZone={timezone ?? browserTimeZone} className="mt-1" />
        )}
      </CardContent>
    </Card>
  );
}
