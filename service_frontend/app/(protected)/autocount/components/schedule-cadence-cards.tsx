'use client';

import type { ReactNode } from 'react';
import { CalendarClock, RefreshCcw } from 'lucide-react';
import type { AutocountScheduleCadence } from '@/types/autocount';
import {
  incrementalFloorMinutes,
  RECONCILE_MODE_OPTIONS,
  validateIncrementalMinutes,
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
}: ScheduleCadenceCardsProps) {
  const { formatDateTime } = useDatetime();
  const floor = incrementalFloorMinutes(hasWatermark);
  const incrementalError =
    fieldErrors.incrementalMinutes ??
    validateIncrementalMinutes(value.incrementalMinutes, hasWatermark);
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
                  min={floor}
                  step={1}
                  className="w-24"
                  value={
                    Number.isFinite(value.incrementalMinutes)
                      ? value.incrementalMinutes
                      : ''
                  }
                  onChange={(e) =>
                    onChange({
                      incrementalMinutes:
                        e.target.value === '' ? NaN : Number(e.target.value),
                    })
                  }
                  aria-invalid={Boolean(incrementalError)}
                  data-testid={id('incremental-minutes')}
                />
              ) : (
                <span className="text-sm font-medium">
                  {value.incrementalMinutes}
                </span>
              )}
              <span className="text-sm text-muted-foreground">minutes</span>
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
              <span className="text-xs text-muted-foreground">UTC</span>
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
