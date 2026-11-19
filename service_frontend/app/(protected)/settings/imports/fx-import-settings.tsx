'use client';

/**
 * Settings > Imports with the Foundryx UIUX switch on (slice W4-SETTINGS).
 * The same two caps and the same request as with the switch off; what
 * changes is how it reads:
 * - "Save import settings" is the page's red action (today's button, in the
 *   page header).
 * - Both caps are steppers held to whole numbers inside today's ranges (rows
 *   1-1,000,000, file size 1-1024 MB), so a value the switch-off page would
 *   refuse cannot be entered.
 * - Saving ends with a done toast. Undo is offered only when the earlier caps
 *   were this workspace's own: the API has no way back to the deployment
 *   defaults, so writing the defaults' numbers back would not undo.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { toast } from '@/lib/toast';
import { importService, type ImportSettings } from '@/services/import-service';
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

interface Caps {
  maxRows: number;
  maxFileMb: number;
}

export function FxImportSettings() {
  const byWhom = useFxUserName();
  const [caps, setCaps] = useState<Caps | null>(null);
  const [saved, setSaved] = useState<ImportSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const apply = (s: ImportSettings) => {
    setCaps({ maxRows: s.maxRows, maxFileMb: s.maxFileMb });
    setSaved(s);
  };

  useEffect(() => {
    importService
      .getSettings()
      .then(apply)
      .catch(() => undefined)
      .finally(() => setLoading(false));
  }, []);

  const onSave = async () => {
    if (!caps) return;
    const before = saved;
    setSaving(true);
    try {
      apply(await importService.updateSettings(caps.maxRows, caps.maxFileMb));
      toast.fxDone({
        what: 'Import limits saved',
        byWhom,
        undo:
          before && !before.isDefault
            ? () =>
                void importService
                  .updateSettings(before.maxRows, before.maxFileMb)
                  .then(apply)
                  .catch(() => toast.error("Couldn't undo. The new limits stay."))
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
  const ready = !loading && caps !== null;
  const main = useMemo<FxMainActionSpec | null>(
    () =>
      ready
        ? {
            id: 'save-import-settings',
            label: 'Save import settings',
            onClick: () => void onSaveRef.current(),
            working: saving,
          }
        : null,
    [ready, saving],
  );
  useRegisterMainAction(main);

  if (loading) return <Skeleton className="h-48 w-full" />;

  return (
    <Card>
      <CardHeader>
        <CardHeading>
          <CardTitle>Import limits</CardTitle>
        </CardHeading>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        {caps === null ? (
          <p className="text-sm text-(--fx-ink-2)">Couldn&apos;t load the settings.</p>
        ) : (
          <>
            <FxField label="Max rows per import" id="fx-max-rows">
              <FxStepper
                id="fx-max-rows"
                value={caps.maxRows}
                onChange={(n) => setCaps((c) => (c ? { ...c, maxRows: n } : c))}
                min={1}
                max={1_000_000}
                step={1000}
                precision={0}
                className="[&_input]:w-20"
              />
            </FxField>
            <div className="flex flex-col gap-1.5">
              <FxField label="Max file size" id="fx-max-mb">
                <FxStepper
                  id="fx-max-mb"
                  value={caps.maxFileMb}
                  onChange={(n) => setCaps((c) => (c ? { ...c, maxFileMb: n } : c))}
                  min={1}
                  max={1024}
                  step={1}
                  precision={0}
                  unit="MB"
                />
              </FxField>
              <p className="text-xs text-(--fx-ink-3)">
                {saved?.isDefault ? 'Using the deployment defaults.' : 'Custom for this workspace.'}
              </p>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
