'use client';

import { useState, type ReactNode } from 'react';
import { CalendarClock, Moon, RefreshCcw } from 'lucide-react';
import type { AutocountEtlSourceConfig, AutocountScheduleCadence } from '@/types/autocount';
import {
  incrementalFloorMinutes,
  DEFAULT_INCREMENTAL_SECONDS,
  INCREMENTAL_UNIT_OPTIONS,
  MIN_INCREMENTAL_SECONDS,
  quietHoursErrors,
  RECONCILE_MODE_OPTIONS,
  RECONCILE_TIMEZONE_OPTIONS,
  reconcileTimezoneLabel,
  validateIncrementalMinutes,
  validateIncrementalSeconds,
  validateReconcileAt,
  validateReconcileHours,
} from '@/lib/autocount-etl';
import { useDatetime } from '@/hooks/use-datetime';
import { Badge } from '@/components/ui/badge';
import {
  Card,
  CardContent,
  CardHeader,
  CardHeading,
  CardTitle,
} from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { SearchSelect } from '@/components/platform/search-select';

export interface ScheduleCadenceCardsProps {
  editing: boolean;
  value: AutocountScheduleCadence;
  onChange: (patch: Partial<AutocountScheduleCadence>) => void;
  /** Picks the incremental floor (1 min with a watermark, 5 without). */
  hasWatermark: boolean;
  /** Server 422s from the last save; win over the live client mirror. */
  fieldErrors?: Record<string, string>;
  /** Shown as a "Next ..." badge only when set (an armed schedule). */
  nextIncrementalAt?: string | null;
  nextReconcileAt?: string | null;
  incrementalTitle?: string;
  reconcileTitle?: string;
  /** Prefix for element ids + `data-testid`s (`etl` on the Entities tab). */
  idPrefix?: string;
  /** Grid classes - the Entities tab lays three cards out at `md`. */
  className?: string;
  /** Extra cards rendered in the same grid (the Entities delete guard). */
  children?: ReactNode;
  /** Extra fields inside the incremental / reconcile card, after the
   * cadence fields (the Document feeds' read window, DOC-FEED-WINDOW). */
  incrementalExtra?: ReactNode;
  reconcileExtra?: ReactNode;
  /** SS-SO-FAST-QUEUE - the daily time's zone is editable (ETL tasks). Off =
   * a fixed "UTC" label (Document feeds, whose sweep reads UTC). */
  timezoneEditable?: boolean;
  /** SS-SO-FAST-QUEUE - the incremental may be set in seconds (document
   * tasks with a watermark); off = minutes only. */
  secondsAllowed?: boolean;
}

/** Live mirror of every cadence rule - the same messages the cards render.
 * Callers gate Save on it; the server re-validates on save regardless. */
export function scheduleCadenceErrors(
  value: AutocountScheduleCadence,
  hasWatermark: boolean,
): Record<string, string> {
  const errors: Record<string, string> = {};
  const incremental = validateIncrementalMinutes(value.incrementalMinutes, hasWatermark);
  if (incremental) errors.incrementalMinutes = incremental;
  const seconds = validateIncrementalSeconds(value.incrementalSeconds);
  if (seconds) errors.incrementalSeconds = seconds;
  if (value.reconcileMode === 'dailyAt') {
    const at = validateReconcileAt(value.reconcileAt);
    if (at) errors.reconcileAt = at;
  } else {
    const hours = validateReconcileHours(value.reconcileHours);
    if (hours) errors.reconcileHours = hours;
  }
  return errors;
}

/**
 * The Incremental + Reconcile cadence cards (plan 22 §3, AC-22-12..17) -
 * ONE component shared by the Entities task editor's Schedule tab and the
 * Document feeds Configure dialog (sprint-5/19, AC-19-10/11), so a cadence is
 * edited, validated and displayed identically wherever it is configured.
 */
export function ScheduleCadenceCards({
  editing,
  value,
  onChange,
  hasWatermark,
  fieldErrors = {},
  nextIncrementalAt = null,
  nextReconcileAt = null,
  incrementalTitle = 'Incremental',
  reconcileTitle = 'Reconcile',
  idPrefix = 'etl',
  className = 'grid gap-4 md:grid-cols-3',
  children,
  incrementalExtra,
  reconcileExtra,
  timezoneEditable = false,
  secondsAllowed = false,
}: ScheduleCadenceCardsProps) {
  const { formatDateTime } = useDatetime();
  const floor = incrementalFloorMinutes(hasWatermark);
  const inSeconds =
    secondsAllowed &&
    value.incrementalSeconds !== null &&
    value.incrementalSeconds !== undefined;
  const incrementalError = inSeconds
    ? (fieldErrors.incrementalSeconds ?? validateIncrementalSeconds(value.incrementalSeconds))
    : (fieldErrors.incrementalMinutes ??
      fieldErrors.incrementalSeconds ??
      validateIncrementalMinutes(value.incrementalMinutes, hasWatermark));
  const incrementalValue = inSeconds ? value.incrementalSeconds : value.incrementalMinutes;
  const reconcileAtError =
    value.reconcileMode === 'dailyAt'
      ? (fieldErrors.reconcileAt ?? validateReconcileAt(value.reconcileAt))
      : null;
  const reconcileHoursError =
    value.reconcileMode === 'interval'
      ? (fieldErrors.reconcileHours ?? validateReconcileHours(value.reconcileHours))
      : null;
  const id = (suffix: string) => `${idPrefix}-${suffix}`;

  return (
    <div className={className}>
      <Card>
        <CardHeader>
          <CardHeading>
            <CardTitle className="flex items-center gap-2 text-sm">
              <RefreshCcw className="size-4" />
              {incrementalTitle}
            </CardTitle>
          </CardHeading>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={id('incremental-minutes')}>Every</Label>
            <div className="flex items-center gap-2">
              {editing ? (
                <Input
                  id={id('incremental-minutes')}
                  type="number"
                  min={inSeconds ? MIN_INCREMENTAL_SECONDS : floor}
                  step={1}
                  className="w-24"
                  value={
                    incrementalValue !== null &&
                    incrementalValue !== undefined &&
                    Number.isFinite(incrementalValue)
                      ? incrementalValue
                      : ''
                  }
                  onChange={(e) => {
                    const next = e.target.value === '' ? NaN : Number(e.target.value);
                    if (inSeconds) onChange({ incrementalSeconds: next });
                    else onChange({ incrementalMinutes: next });
                  }}
                  aria-invalid={Boolean(incrementalError)}
                  data-testid={id('incremental-minutes')}
                />
              ) : (
                <span className="text-sm font-medium">{incrementalValue}</span>
              )}
              {secondsAllowed && editing ? (
                <SearchSelect
                  options={INCREMENTAL_UNIT_OPTIONS}
                  value={inSeconds ? 'seconds' : 'minutes'}
                  onChange={(unit) =>
                    onChange({
                      incrementalSeconds:
                        unit === 'seconds' ? DEFAULT_INCREMENTAL_SECONDS : null,
                    })
                  }
                  ariaLabel={`${incrementalTitle} unit`}
                />
              ) : (
                <span
                  className="text-sm text-muted-foreground"
                  data-testid={id('incremental-unit')}
                >
                  {inSeconds ? 'seconds' : 'minutes'}
                </span>
              )}
            </div>
            {incrementalError && (
              <p
                className="text-xs text-destructive"
                data-testid={id('incremental-error')}
              >
                {incrementalError}
              </p>
            )}
          </div>
          {incrementalExtra}
          {nextIncrementalAt && (
            <Badge
              variant="secondary"
              appearance="light"
              size="sm"
              data-testid={id('next-incremental-badge')}
            >
              Next {formatDateTime(nextIncrementalAt)}
            </Badge>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardHeading>
            <CardTitle className="flex items-center gap-2 text-sm">
              <CalendarClock className="size-4" />
              {reconcileTitle}
            </CardTitle>
          </CardHeading>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={id('reconcile-mode')}>Mode</Label>
            {editing ? (
              <SearchSelect
                options={RECONCILE_MODE_OPTIONS}
                value={value.reconcileMode}
                onChange={(v) =>
                  onChange({
                    reconcileMode: v as AutocountScheduleCadence['reconcileMode'],
                  })
                }
                ariaLabel={`${reconcileTitle} mode`}
              />
            ) : (
              <span className="text-sm font-medium">
                {
                  RECONCILE_MODE_OPTIONS.find(
                    (o) => o.value === value.reconcileMode,
                  )?.label
                }
              </span>
            )}
          </div>

          {value.reconcileMode === 'dailyAt' ? (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor={id('reconcile-at')}>Time</Label>
              {editing ? (
                <Input
                  id={id('reconcile-at')}
                  type="time"
                  className="w-32"
                  value={value.reconcileAt ?? ''}
                  onChange={(e) => onChange({ reconcileAt: e.target.value || null })}
                  aria-invalid={Boolean(reconcileAtError)}
                  data-testid={id('reconcile-at')}
                />
              ) : (
                <span className="text-sm font-medium">
                  {value.reconcileAt ?? '-'}
                </span>
              )}
              {timezoneEditable && editing ? (
                <SearchSelect
                  options={RECONCILE_TIMEZONE_OPTIONS}
                  value={value.reconcileTimezone || 'UTC'}
                  onChange={(v) => onChange({ reconcileTimezone: v })}
                  ariaLabel={`${reconcileTitle} time zone`}
                />
              ) : (
                <span
                  className="text-xs text-muted-foreground"
                  data-testid={id('reconcile-timezone')}
                >
                  {timezoneEditable ? reconcileTimezoneLabel(value.reconcileTimezone) : 'UTC'}
                </span>
              )}
              {reconcileAtError && (
                <p
                  className="text-xs text-destructive"
                  data-testid={id('reconcile-at-error')}
                >
                  {reconcileAtError}
                </p>
              )}
            </div>
          ) : (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor={id('reconcile-hours')}>Every</Label>
              <div className="flex items-center gap-2">
                {editing ? (
                  <Input
                    id={id('reconcile-hours')}
                    type="number"
                    min={1}
                    step={1}
                    className="w-24"
                    value={value.reconcileHours ?? ''}
                    onChange={(e) =>
                      onChange({
                        reconcileHours:
                          e.target.value === '' ? null : Number(e.target.value),
                      })
                    }
                    aria-invalid={Boolean(reconcileHoursError)}
                    data-testid={id('reconcile-hours')}
                  />
                ) : (
                  <span className="text-sm font-medium">
                    {value.reconcileHours ?? '-'}
                  </span>
                )}
                <span className="text-sm text-muted-foreground">hours</span>
              </div>
              {reconcileHoursError && (
                <p
                  className="text-xs text-destructive"
                  data-testid={id('reconcile-hours-error')}
                >
                  {reconcileHoursError}
                </p>
              )}
            </div>
          )}

          {reconcileExtra}

          {nextReconcileAt && (
            <Badge
              variant="secondary"
              appearance="light"
              size="sm"
              data-testid={id('next-reconcile-badge')}
            >
              Next {formatDateTime(nextReconcileAt)}
            </Badge>
          )}
        </CardContent>
      </Card>

      {children}
    </div>
  );
}

export interface OffHoursCardProps {
  editing: boolean;
  value: Pick<
    AutocountEtlSourceConfig,
    'quietHoursEnabled' | 'quietHoursStart' | 'quietHoursEnd' | 'quietHoursTimezone'
  >;
  onChange: (patch: Partial<AutocountEtlSourceConfig>) => void;
  /** Server 422s from the last save; win over the live client mirror. */
  fieldErrors?: Record<string, string>;
  idPrefix?: string;
}

/**
 * SS-QUIET-HOURS - a task's off-hours window (no scheduled incremental, so
 * no AutoCount query, inside it). Same card shell as the cadence cards; laid
 * into the Schedule tab's cadence grid.
 */

/** Shared empty error map (default prop + "no server errors"). */
const NO_FIELD_ERRORS: Record<string, string> = {};

export function OffHoursCard({
  editing,
  value,
  onChange,
  fieldErrors = NO_FIELD_ERRORS,
  idPrefix = 'etl',
}: OffHoursCardProps) {
  const id = (suffix: string) => `${idPrefix}-${suffix}`;
  const enabled = value.quietHoursEnabled === true;
  const live = quietHoursErrors(value);
  // A refused save's server errors describe the window AS SUBMITTED: keep a
  // snapshot of the window per server answer, and once the window differs
  // from that snapshot fall back to the live check (crew browser pass, PR
  // 228). The answer is compared by its off-hours error TEXT, never by
  // object identity: the task editor merges its error maps into a new
  // object on every render.
  const windowKey = [
    value.quietHoursEnabled === true,
    value.quietHoursStart ?? '',
    value.quietHoursEnd ?? '',
  ].join('|');
  const errorsKey = [
    fieldErrors.quietHoursStart ?? '',
    fieldErrors.quietHoursEnd ?? '',
    fieldErrors.quietHoursTimezone ?? '',
  ].join('|');
  const [submitted, setSubmitted] = useState({ errors: errorsKey, key: windowKey });
  if (submitted.errors !== errorsKey) {
    setSubmitted({ errors: errorsKey, key: windowKey });
  }
  const server = submitted.key === windowKey ? fieldErrors : NO_FIELD_ERRORS;
  const startError = server.quietHoursStart ?? live.quietHoursStart ?? null;
  const endError = server.quietHoursEnd ?? live.quietHoursEnd ?? null;
  const zone = reconcileTimezoneLabel(value.quietHoursTimezone || 'Asia/Kuala_Lumpur');

  const timeField = (
    key: 'quietHoursStart' | 'quietHoursEnd',
    label: string,
    error: string | null,
  ) => (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id(`quiet-${key === 'quietHoursStart' ? 'start' : 'end'}`)}>
        {label}
      </Label>
      {editing ? (
        <Input
          id={id(`quiet-${key === 'quietHoursStart' ? 'start' : 'end'}`)}
          type="time"
          className="w-32"
          value={value[key] ?? ''}
          disabled={!enabled}
          onChange={(e) => onChange({ [key]: e.target.value || null })}
          aria-invalid={Boolean(error)}
          data-testid={id(`quiet-${key === 'quietHoursStart' ? 'start' : 'end'}`)}
        />
      ) : (
        <span className="text-sm font-medium">{value[key] ?? '-'}</span>
      )}
      {error && enabled && (
        <p className="text-xs text-destructive" data-testid={id(`quiet-${key === 'quietHoursStart' ? 'start' : 'end'}-error`)}>
          {error}
        </p>
      )}
    </div>
  );

  return (
    <Card data-testid={id('off-hours')}>
      <CardHeader>
        <CardHeading>
          <CardTitle className="flex items-center gap-2 text-sm">
            <Moon className="size-4" />
            Off hours
          </CardTitle>
        </CardHeading>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <Switch
            id={id('quiet-enabled')}
            checked={enabled}
            disabled={!editing}
            onCheckedChange={(checked) =>
              onChange({
                quietHoursEnabled: checked,
                quietHoursTimezone: value.quietHoursTimezone || 'Asia/Kuala_Lumpur',
              })
            }
            aria-label="Off hours"
            data-testid={id('quiet-enabled')}
          />
          <Label htmlFor={id('quiet-enabled')}>{enabled ? 'On' : 'Off'}</Label>
        </div>
        <div className="flex flex-wrap gap-4">
          {timeField('quietHoursStart', 'From', startError)}
          {timeField('quietHoursEnd', 'To', endError)}
        </div>
        <span className="text-xs text-muted-foreground" data-testid={id('quiet-timezone')}>
          {zone}, every day
        </span>
      </CardContent>
    </Card>
  );
}
