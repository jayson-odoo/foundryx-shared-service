'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { toast } from '@/lib/toast';
import { useIntegrationLogSettings } from '@/hooks/use-integration-log-settings';
import {
  Card,
  CardContent,
  CardHeader,
  CardHeading,
  CardTitle,
} from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import {
  useRegisterMainAction,
  type FxMainActionSpec,
} from '@/components/fx/actions/page-actions-context';
import { pulseFxTarget } from '@/components/fx/actions/pulse';
import { FxField, FxStepper } from '@/components/fx/fields';
import { useFxByWhom } from '@/components/fx/pages/w3-logs/fx-log-parts';

const FX_DAYS_TARGET = 'log-retention-days';

/**
 * The retention window a typed value saves, or null when it is not a whole
 * number of days from 1 to 3650 (the same rule as with the switch off).
 */
export function fxRetentionDays(value: number | null): number | null {
  if (value === null || !Number.isInteger(value) || value < 1 || value > 3650) return null;
  return value;
}

/**
 * The retention form with the Foundryx UIUX switch on: the days as a
 * stepper, "Save log settings" as the page's red action (never repeated on
 * the page), the same save request as with the switch off, and a done toast.
 * Its Undo writes the previous window back, offered only when that window
 * was a custom one: the deployment default cannot be restored by a save.
 */
export function FxLogRetentionForm() {
  const { settings, isLoading, isSaving, save } = useIntegrationLogSettings();
  const byWhom = useFxByWhom();
  const [days, setDays] = useState<number | null>(null);
  const [wrong, setWrong] = useState(false);

  useEffect(() => {
    if (settings) setDays(settings.retentionDays);
  }, [settings]);

  const onSave = async () => {
    const n = fxRetentionDays(days);
    if (n === null) {
      setWrong(true);
      pulseFxTarget(FX_DAYS_TARGET);
      return;
    }
    setWrong(false);
    const before = settings;
    try {
      await save(n);
      toast.fxDone({
        what: `Developer logs kept for ${n} ${n === 1 ? 'day' : 'days'}`,
        byWhom,
        undo:
          before && !before.isDefault && before.retentionDays !== n
            ? () =>
                void save(before.retentionDays).catch(() =>
                  toast.error("Couldn't undo. The new window stays."),
                )
            : undefined,
      });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not save settings.');
    }
  };
  const onSaveRef = useRef(onSave);
  onSaveRef.current = onSave;

  const ready = !isLoading && days !== null;
  const main = useMemo<FxMainActionSpec | null>(
    () =>
      ready
        ? {
            id: 'save-log-settings',
            label: 'Save log settings',
            fullLabel: days !== null ? `Keep developer logs for ${days} ${days === 1 ? 'day' : 'days'}` : undefined,
            onClick: () => void onSaveRef.current(),
            working: isSaving,
          }
        : null,
    [ready, days, isSaving],
  );
  useRegisterMainAction(main);

  return (
    <Card>
      <CardHeader>
        <CardHeading>
          <CardTitle>Log retention</CardTitle>
        </CardHeading>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex max-w-xs flex-col gap-1.5">
          <Label htmlFor="log-retention-days">Keep developer logs for</Label>
          <FxField message={wrong ? 'Enter a whole number of days between 1 and 3650.' : undefined}>
            <div data-fx-pulse-target={FX_DAYS_TARGET}>
              <FxStepper
                id="log-retention-days"
                value={days ?? 1}
                min={1}
                max={3650}
                step={1}
                unit="days"
                disabled={isLoading || days === null}
                onChange={(n) => {
                  setDays(n);
                  if (wrong) setWrong(false);
                }}
              />
            </div>
          </FxField>
          <p className="text-xs text-(--fx-ink-3)">
            {settings?.isDefault ? 'Using the deployment default.' : 'Custom for this workspace.'}
          </p>
        </div>
      </CardContent>
    </Card>
  );
}
