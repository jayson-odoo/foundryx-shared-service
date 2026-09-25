'use client';

import { CalendarClock, RefreshCcw, ShieldAlert, TriangleAlert } from 'lucide-react';
import type {
  AutocountDeliveryMode,
  AutocountEtlSourceConfig,
  AutocountEtlTask,
} from '@/types/autocount';
import {
  incrementalFloorMinutes,
  isDocumentEntity,
  pushGateWarning,
  RECONCILE_MODE_OPTIONS,
  validateIncrementalMinutes,
  validateReconcileAt,
  validateReconcileHours,
} from '@/lib/autocount-etl';
import { useDatetime } from '@/hooks/use-datetime';
import { Alert, AlertIcon, AlertTitle } from '@/components/ui/alert';
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
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { SearchSelect } from '@/components/platform/search-select';
import { StatusBadge } from '@/components/platform/status-badge';
import { AC_DELIVERY_MODE_REGISTRY } from '../../../../../components/autocount-meta';

export interface ScheduleTabProps {
  editing: boolean;
  entityType: string;
  config: AutocountEtlSourceConfig;
  onChange: (patch: Partial<AutocountEtlSourceConfig>) => void;
  task: AutocountEtlTask;
  /** Per-field 422 errors from the last save (AC-22-12); wins over the live
   * client mirror once the server has spoken. */
  fieldErrors: Record<string, string>;
  /** The tab's OWN draft (sprint-5/10, AC-10-11/16) - saved through a
   * separate PUT, never `sourceConfig`. */
  deliveryMode: AutocountDeliveryMode;
  onDeliveryModeChange: (mode: AutocountDeliveryMode) => void;
}

const DELIVERY_SEGMENT_CLASS =
  'data-[state=on]:bg-primary data-[state=on]:text-primary-foreground data-[state=on]:border-primary';

/**
 * The task editor's Schedule tab (plan 22 §3, AC-22-12..17): the incremental
 * interval, the reconcile cadence (daily-at or every-N-hours), and a
 * read-only summary of the delete guard. The fields already live on
 * `sourceConfig` and save through the SAME PUT the Query tab uses (one Save,
 * shell dirty-guard) - this tab only renders + live-validates them. The
 * floors mirror the save-time guard exactly (`lib/autocount-etl.ts`); the
 * server re-validates on save regardless.
 */
export function ScheduleTab({
  editing,
  entityType,
  config,
  onChange,
  task,
  fieldErrors,
  deliveryMode,
  onDeliveryModeChange,
}: ScheduleTabProps) {
  const { formatDateTime } = useDatetime();
  const hasWatermark = Boolean(config.watermarkColumn);
  const floor = incrementalFloorMinutes(hasWatermark);
  const incrementalError =
    fieldErrors.incrementalMinutes ??
    validateIncrementalMinutes(config.incrementalMinutes, hasWatermark);
  const reconcileAtError =
    config.reconcileMode === 'dailyAt'
      ? (fieldErrors.reconcileAt ?? validateReconcileAt(config.reconcileAt))
      : null;
  const reconcileHoursError =
    config.reconcileMode === 'interval'
      ? (fieldErrors.reconcileHours ??
        validateReconcileHours(config.reconcileHours))
      : null;
  const isActive = task.etlStatus === 'active';
  const isDocument = isDocumentEntity(entityType);
  // sprint-5/13 (D18, AC-13-40) - the push gate is decided EXCLUSIVELY by the
  // backend's `task.pushGate`, never a hardcoded entity list (foolproof-UI:
  // only offer valid options). No toggle while shut, a read-only badge
  // naming the CURRENT mode instead - the toggle appears on its own the
  // moment the gate opens, with no frontend code change.
  const pushGateShut = task.pushGate != null;
  // sprint-5/13 S2 fix - rollback to pull must never be hidden. If the SAVED
  // delivery mode is already push, the toggle always renders even when the
  // gate reports shut (a contract regression after activation, say):
  // pull-on-request is always a valid choice. Guarded on both sides - the
  // backend also returns `pushGate: null` for push-mode tasks.
  const savedDeliveryModeIsPush = task.deliveryMode === 'push';
  const showToggle = !pushGateShut || savedDeliveryModeIsPush;
  const isPull = deliveryMode === 'pull';

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-2">
        <div className="flex items-center gap-3" data-testid="etl-delivery-mode">
          <Label className="text-sm font-medium">Delivery</Label>
          {!showToggle ? (
            <StatusBadge status={deliveryMode} registry={AC_DELIVERY_MODE_REGISTRY} />
          ) : (
            <ToggleGroup
              type="single"
              size="sm"
              variant="outline"
              value={deliveryMode}
              onValueChange={(value) => {
                if (value === 'push' || value === 'pull')
                  onDeliveryModeChange(value);
              }}
              disabled={!editing}
              aria-label="Delivery"
            >
              <ToggleGroupItem
                value="push"
                className={DELIVERY_SEGMENT_CLASS}
                data-testid="etl-delivery-push"
              >
                Push
              </ToggleGroupItem>
              <ToggleGroupItem
                value="pull"
                className={DELIVERY_SEGMENT_CLASS}
                data-testid="etl-delivery-pull"
              >
                Pull on request
              </ToggleGroupItem>
            </ToggleGroup>
          )}
        </div>
        {pushGateShut && task.pushGate && (
          <Alert variant="warning" appearance="light" data-testid="etl-push-gate-warning">
            <AlertIcon>
              <TriangleAlert />
            </AlertIcon>
            <AlertTitle>{pushGateWarning(task.pushGate)}</AlertTitle>
          </Alert>
        )}
      </div>

      {!isPull && (
        <div className="grid gap-4 md:grid-cols-3">
          <Card>
            <CardHeader>
              <CardHeading>
                <CardTitle className="flex items-center gap-2 text-sm">
                  <RefreshCcw className="size-4" />
                  Incremental
                </CardTitle>
              </CardHeading>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="etl-incremental-minutes">Every</Label>
                <div className="flex items-center gap-2">
                  {editing ? (
                    <Input
                      id="etl-incremental-minutes"
                      type="number"
                      min={floor}
                      step={1}
                      className="w-24"
                      value={
                        Number.isFinite(config.incrementalMinutes)
                          ? config.incrementalMinutes
                          : ''
                      }
                      onChange={(e) =>
                        onChange({
                          incrementalMinutes:
                            e.target.value === ''
                              ? NaN
                              : Number(e.target.value),
                        })
                      }
                      aria-invalid={Boolean(incrementalError)}
                      data-testid="etl-incremental-minutes"
                    />
                  ) : (
                    <span className="text-sm font-medium">
                      {config.incrementalMinutes}
                    </span>
                  )}
                  <span className="text-sm text-muted-foreground">minutes</span>
                </div>
                {incrementalError && (
                  <p
                    className="text-xs text-destructive"
                    data-testid="etl-incremental-error"
                  >
                    {incrementalError}
                  </p>
                )}
              </div>
              {isActive && task.nextIncrementalAt && (
                <Badge
                  variant="secondary"
                  appearance="light"
                  size="sm"
                  data-testid="etl-next-incremental-badge"
                >
                  Next {formatDateTime(task.nextIncrementalAt)}
                </Badge>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardHeading>
                <CardTitle className="flex items-center gap-2 text-sm">
                  <CalendarClock className="size-4" />
                  Reconcile
                </CardTitle>
              </CardHeading>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="etl-reconcile-mode">Mode</Label>
                {editing ? (
                  <SearchSelect
                    options={RECONCILE_MODE_OPTIONS}
                    value={config.reconcileMode}
                    onChange={(v) =>
                      onChange({
                        reconcileMode:
                          v as AutocountEtlSourceConfig['reconcileMode'],
                      })
                    }
                    ariaLabel="Reconcile mode"
                  />
                ) : (
                  <span className="text-sm font-medium">
                    {
                      RECONCILE_MODE_OPTIONS.find(
                        (o) => o.value === config.reconcileMode,
                      )?.label
                    }
                  </span>
                )}
              </div>

              {config.reconcileMode === 'dailyAt' ? (
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="etl-reconcile-at">Time</Label>
                  {editing ? (
                    <Input
                      id="etl-reconcile-at"
                      type="time"
                      className="w-32"
                      value={config.reconcileAt ?? ''}
                      onChange={(e) =>
                        onChange({ reconcileAt: e.target.value || null })
                      }
                      aria-invalid={Boolean(reconcileAtError)}
                      data-testid="etl-reconcile-at"
                    />
                  ) : (
                    <span className="text-sm font-medium">
                      {config.reconcileAt ?? '-'}
                    </span>
                  )}
                  <span className="text-xs text-muted-foreground">UTC</span>
                  {reconcileAtError && (
                    <p
                      className="text-xs text-destructive"
                      data-testid="etl-reconcile-at-error"
                    >
                      {reconcileAtError}
                    </p>
                  )}
                </div>
              ) : (
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="etl-reconcile-hours">Every</Label>
                  <div className="flex items-center gap-2">
                    {editing ? (
                      <Input
                        id="etl-reconcile-hours"
                        type="number"
                        min={1}
                        step={1}
                        className="w-24"
                        value={config.reconcileHours ?? ''}
                        onChange={(e) =>
                          onChange({
                            reconcileHours:
                              e.target.value === ''
                                ? null
                                : Number(e.target.value),
                          })
                        }
                        aria-invalid={Boolean(reconcileHoursError)}
                        data-testid="etl-reconcile-hours"
                      />
                    ) : (
                      <span className="text-sm font-medium">
                        {config.reconcileHours ?? '-'}
                      </span>
                    )}
                    <span className="text-sm text-muted-foreground">hours</span>
                  </div>
                  {reconcileHoursError && (
                    <p
                      className="text-xs text-destructive"
                      data-testid="etl-reconcile-hours-error"
                    >
                      {reconcileHoursError}
                    </p>
                  )}
                </div>
              )}

              {isActive && task.nextReconcileAt && (
                <Badge
                  variant="secondary"
                  appearance="light"
                  size="sm"
                  data-testid="etl-next-reconcile-badge"
                >
                  Next {formatDateTime(task.nextReconcileAt)}
                </Badge>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardHeading>
                <CardTitle className="flex items-center gap-2 text-sm">
                  <ShieldAlert className="size-4" />
                  Delete guard
                </CardTitle>
              </CardHeading>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              <Badge
                variant="secondary"
                appearance="light"
                size="sm"
                data-testid="etl-delete-guard-threshold"
              >
                20% of known rows (minimum 50)
              </Badge>
              {isDocument && (
                <div className="flex flex-col gap-1">
                  <Label>From date</Label>
                  <span
                    className="text-sm font-medium"
                    data-testid="etl-schedule-from-date"
                  >
                    {config.fromDate ?? '-'}
                  </span>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
