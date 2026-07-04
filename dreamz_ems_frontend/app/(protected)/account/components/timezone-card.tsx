'use client';

import { useMemo } from 'react';
import { AlertCircle, Globe } from 'lucide-react';
import { toast } from 'sonner';
import { getTimeZones } from '@/i18n/timezones';
import { SearchSelect } from '@/components/platform/search-select/search-select';
import { Alert, AlertIcon, AlertTitle } from '@/components/ui/alert';
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { useTimezonePreference } from '@/hooks/use-timezone-preference';

/** Sentinel option — clears the preference back to the browser tz. */
const BROWSER_DEFAULT = '__browser__';

/**
 * Timezone preference card (plan sprint-2/05) — timestamps everywhere render
 * in this timezone via useDatetime; no preference = browser tz.
 */
export function TimezoneCard() {
  const { timezone, browserTimeZone, isSaving, error, save } =
    useTimezonePreference();

  // ~400 Intl formatter constructions — compute once.
  const options = useMemo(
    () => [
      {
        value: BROWSER_DEFAULT,
        label: `Browser default — ${browserTimeZone.replace(/_/g, ' ')}`,
      },
      ...getTimeZones(),
    ],
    [browserTimeZone],
  );

  const onChange = async (value: string) => {
    const next = value === BROWSER_DEFAULT ? null : value;
    if (next === timezone) return;
    const ok = await save(next);
    if (ok) toast.success('Timezone saved.');
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Preferences</CardTitle>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-3">
            <Globe className="size-4 text-muted-foreground" />
            <div className="flex flex-col">
              <span className="text-sm font-medium text-mono">Timezone</span>
              <span className="text-xs text-muted-foreground">
                Dates and times across the app are shown in this timezone.
              </span>
            </div>
          </div>
          <SearchSelect
            options={options}
            value={timezone ?? BROWSER_DEFAULT}
            onChange={onChange}
            disabled={isSaving}
            placeholder="Select a timezone…"
            searchPlaceholder="Search timezones…"
            ariaLabel="Timezone"
          />
          {error && (
            <Alert variant="destructive">
              <AlertIcon>
                <AlertCircle />
              </AlertIcon>
              <AlertTitle>{error}</AlertTitle>
            </Alert>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
