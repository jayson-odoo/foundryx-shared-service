'use client';

/**
 * Business hours tab (plan 31 S6, AC-WFP-55/63) - a per-workspace weekly
 * schedule + IANA timezone, gated `workspaces.manage` for edits (read-only
 * for `workspaces.read`-only viewers, same as every other workspace tab).
 * Wired into the parent form's global Edit toggle + dirty guard through an
 * imperative `BusinessHoursController` (mirrors the Lifecycle tab's
 * `LayoutController` - this endpoint saves separately from the workspace's
 * own PATCH, so it needs its own controller, not the shared status-engine
 * one).
 */
import { useEffect, useMemo } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { SearchSelect } from '@/components/platform/search-select';
import { FormRow } from '@/components/platform/resource-form';
import {
  BUSINESS_HOURS_WEEKDAYS,
  type BusinessHoursWeekday,
  type BusinessHoursWindow,
} from '@/types/omnichannel';
import { useBusinessHours } from './use-business-hours';

export interface BusinessHoursController {
  save: () => Promise<boolean>;
  discard: () => void;
}

const WEEKDAY_LABELS: Record<BusinessHoursWeekday, string> = {
  mon: 'Monday',
  tue: 'Tuesday',
  wed: 'Wednesday',
  thu: 'Thursday',
  fri: 'Friday',
  sat: 'Saturday',
  sun: 'Sunday',
};

let cachedTimezones: string[] | null = null;
function timezoneOptions(): { value: string; label: string }[] {
  if (!cachedTimezones) {
    try {
      cachedTimezones = Intl.supportedValuesOf('timeZone');
    } catch {
      cachedTimezones = ['UTC'];
    }
  }
  return cachedTimezones.map((tz) => ({ value: tz, label: tz.replace(/_/g, ' ') }));
}

export interface WorkspaceBusinessHoursTabProps {
  workspaceId: string | null;
  creating: boolean;
  editing: boolean;
  onDirtyChange?: (dirty: boolean) => void;
  controller?: React.MutableRefObject<BusinessHoursController | null>;
}

export function WorkspaceBusinessHoursTab({
  workspaceId,
  creating,
  editing,
  onDirtyChange,
  controller,
}: WorkspaceBusinessHoursTabProps) {
  const {
    isLoading,
    timezone,
    windows,
    isDirty,
    saveError,
    fieldErrors,
    setTimezone,
    setWindows,
    save,
    discard,
  } = useBusinessHours(creating ? null : workspaceId);

  useEffect(() => {
    onDirtyChange?.(isDirty);
  }, [isDirty, onDirtyChange]);

  useEffect(() => {
    if (controller) controller.current = { save, discard };
  }, [controller, save, discard]);

  const tzOptions = useMemo(timezoneOptions, []);

  if (creating || !workspaceId) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center gap-2 py-16 text-center">
          <p className="text-sm font-medium">Set business hours after creating the workspace</p>
        </CardContent>
      </Card>
    );
  }

  if (isLoading) {
    return (
      <Card>
        <CardContent className="py-12 text-center text-sm text-muted-foreground">Loading…</CardContent>
      </Card>
    );
  }

  function updateDay(day: BusinessHoursWeekday, next: BusinessHoursWindow[]) {
    setWindows({ ...windows, [day]: next });
  }

  function addWindow(day: BusinessHoursWeekday) {
    updateDay(day, [...windows[day], { from: '09:00', to: '18:00' }]);
  }

  function removeWindow(day: BusinessHoursWeekday, index: number) {
    updateDay(
      day,
      windows[day].filter((_, i) => i !== index),
    );
  }

  function changeWindow(day: BusinessHoursWeekday, index: number, patch: Partial<BusinessHoursWindow>) {
    updateDay(
      day,
      windows[day].map((w, i) => (i === index ? { ...w, ...patch } : w)),
    );
  }

  return (
    <Card>
      <CardContent className="flex flex-col gap-4 py-4">
        <FormRow label="Timezone" required={editing}>
          {editing ? (
            <div className="max-w-sm">
              <SearchSelect
                options={tzOptions}
                value={timezone}
                onChange={(v) => setTimezone(v ?? '')}
                ariaLabel="Timezone"
                placeholder="Choose a timezone…"
                searchPlaceholder="Search timezones…"
              />
              {fieldErrors.timezone && (
                <p className="mt-1 text-xs text-destructive" data-testid="business-hours-timezone-error">
                  {fieldErrors.timezone}
                </p>
              )}
            </div>
          ) : (
            <span className="text-sm">{timezone ?? '-'}</span>
          )}
        </FormRow>

        <div className="flex flex-col gap-3" data-testid="business-hours-schedule">
          {BUSINESS_HOURS_WEEKDAYS.map((day) => {
            const rows = windows[day];
            return (
              <div key={day} className="flex flex-col gap-1.5 sm:flex-row sm:gap-4">
                <span className="w-24 shrink-0 pt-1.5 text-sm font-medium text-foreground">
                  {WEEKDAY_LABELS[day]}
                </span>
                <div className="flex flex-1 flex-col gap-2">
                  {rows.length === 0 && !editing && (
                    <span className="text-sm text-muted-foreground">Closed</span>
                  )}
                  {rows.map((row, index) => {
                    const errorKey = `windows.${day}.${index}`;
                    const rowError = fieldErrors[errorKey];
                    return (
                      <div key={index} className="flex flex-col gap-1">
                        <div className="flex flex-wrap items-center gap-2">
                          {editing ? (
                            <>
                              <Input
                                type="time"
                                value={row.from}
                                aria-label={`${WEEKDAY_LABELS[day]} window ${index + 1} start`}
                                aria-invalid={Boolean(rowError)}
                                className="w-28"
                                onChange={(e) => changeWindow(day, index, { from: e.target.value })}
                              />
                              <span className="text-xs text-muted-foreground">to</span>
                              <Input
                                type="time"
                                value={row.to}
                                aria-label={`${WEEKDAY_LABELS[day]} window ${index + 1} end`}
                                aria-invalid={Boolean(rowError)}
                                className="w-28"
                                onChange={(e) => changeWindow(day, index, { to: e.target.value })}
                              />
                              <Button
                                type="button"
                                variant="ghost"
                                size="icon"
                                mode="icon"
                                className="size-8 shrink-0 text-destructive"
                                aria-label={`Remove ${WEEKDAY_LABELS[day]} window ${index + 1}`}
                                onClick={() => removeWindow(day, index)}
                              >
                                <Trash2 className="size-3.5" />
                              </Button>
                            </>
                          ) : (
                            <span className="text-sm">
                              {row.from}–{row.to}
                            </span>
                          )}
                        </div>
                        {rowError && (
                          <p className="text-xs text-destructive" data-testid={`business-hours-error-${errorKey}`}>
                            {rowError}
                          </p>
                        )}
                      </div>
                    );
                  })}
                  {editing && (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="self-start"
                      onClick={() => addWindow(day)}
                      data-testid={`business-hours-add-${day}`}
                    >
                      <Plus className="size-3.5" /> Add window
                    </Button>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        {saveError && !Object.keys(fieldErrors).length && (
          <p className="text-sm text-destructive" data-testid="business-hours-save-error">
            {saveError}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
