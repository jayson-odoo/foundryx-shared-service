'use client';

/**
 * Settings > Workflows with the Foundryx UIUX switch on (slice W4-SETTINGS).
 * The same setting and the same request as with the switch off; what changes
 * is how it reads:
 * - "Save workflow settings" is the page's red action (today's button, in
 *   the page header).
 * - The retention is a stepper held to whole days inside today's range
 *   (1-3650), so a value the switch-off page would refuse cannot be entered.
 * - Saving ends with a done toast. Undo is offered only when the earlier
 *   value was this workspace's own: the API has no way back to the
 *   deployment default, so writing the default's number back would not undo.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { toast } from '@/lib/toast';
import { workflowService } from '@/services/workflow-service';
import {
  Card,
  CardContent,
  CardHeader,
  CardHeading,
  CardTitle,
} from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import {
  useRegisterMainAction,
  type FxMainActionSpec,
} from '@/components/fx/actions/page-actions-context';
import { FxField, FxStepper } from '@/components/fx/fields';
import { useFxUserName } from '../general/fx-settings-bits';

export function FxWorkflowSettings() {
  const byWhom = useFxUserName();
  const [days, setDays] = useState<number | null>(null);
  const [saved, setSaved] = useState<{ days: number; isDefault: boolean } | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    workflowService
      .getSettings()
      .then((s) => {
        setDays(s.runRetentionDays);
        setSaved({ days: s.runRetentionDays, isDefault: s.isDefault });
      })
      .catch(() => undefined)
      .finally(() => setLoading(false));
  }, []);

  const apply = (s: { runRetentionDays: number; isDefault: boolean }) => {
    setDays(s.runRetentionDays);
    setSaved({ days: s.runRetentionDays, isDefault: s.isDefault });
  };

  const onSave = async () => {
    if (days === null) return;
    const before = saved;
    setSaving(true);
    try {
      apply(await workflowService.updateSettings(days));
      toast.fxDone({
        what: `Run history kept for ${days} days`,
        byWhom,
        undo:
          before && !before.isDefault
            ? () =>
                void workflowService
                  .updateSettings(before.days)
                  .then(apply)
                  .catch(() => toast.error("Couldn't undo. The new retention stays."))
            : undefined,
      });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not save settings.');
    } finally {
      setSaving(false);
    }
  };

  const onSaveRef = useRef(onSave);
  onSaveRef.current = onSave;
  const ready = !loading && days !== null;
  const main = useMemo<FxMainActionSpec | null>(
    () =>
      ready
        ? {
            id: 'save-workflow-settings',
            label: 'Save workflow settings',
            onClick: () => void onSaveRef.current(),
            working: saving,
          }
        : null,
    [ready, saving],
  );
  useRegisterMainAction(main);

  if (loading) return <Skeleton className="h-40 w-full" />;

  return (
    <Card>
      <CardHeader>
        <CardHeading>
          <CardTitle>Run retention</CardTitle>
        </CardHeading>
      </CardHeader>
      <CardContent className="flex flex-col gap-1.5">
        {days === null ? (
          <p className="text-sm text-(--fx-ink-2)">Couldn&apos;t load the settings.</p>
        ) : (
          <>
            <FxField label="Keep run history for" id="fx-run-retention">
              <FxStepper
                id="fx-run-retention"
                value={days}
                onChange={setDays}
                min={1}
                max={3650}
                step={1}
                precision={0}
                unit="days"
              />
            </FxField>
            <p className="text-xs text-(--fx-ink-3)">
              {saved?.isDefault ? 'Using the deployment default.' : 'Custom for this workspace.'}
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}
