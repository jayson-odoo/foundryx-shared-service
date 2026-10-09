'use client';

import { ShieldAlert, TriangleAlert } from 'lucide-react';
import type {
  AutocountDeliveryMode,
  AutocountEtlSourceConfig,
  AutocountEtlTask,
} from '@/types/autocount';
import { isDocumentEntity, pushGateWarning } from '@/lib/autocount-etl';
import { Alert, AlertIcon, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import {
  Card,
  CardContent,
  CardHeader,
  CardHeading,
  CardTitle,
} from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { StatusBadge } from '@/components/platform/status-badge';
import { AC_DELIVERY_MODE_REGISTRY } from '../../../../../components/autocount-meta';
import { ScheduleCadenceCards } from '../../../../../components/schedule-cadence-cards';

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
  const hasWatermark = Boolean(config.watermarkColumn);
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
        {fieldErrors.deliveryMode && (
          <p className="text-xs text-destructive" data-testid="etl-delivery-mode-error">
            {fieldErrors.deliveryMode}
          </p>
        )}
      </div>

      {!isPull && (
        <ScheduleCadenceCards
          editing={editing}
          value={config}
          onChange={onChange}
          hasWatermark={hasWatermark}
          fieldErrors={fieldErrors}
          nextIncrementalAt={isActive ? task.nextIncrementalAt : null}
          nextReconcileAt={isActive ? task.nextReconcileAt : null}
        >
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
        </ScheduleCadenceCards>
      )}
    </div>
  );
}
