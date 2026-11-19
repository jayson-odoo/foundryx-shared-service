'use client';

/**
 * Settings > General with the Foundryx UIUX switch on (slice W4-SETTINGS).
 * The same settings and the same requests as with the switch off; what
 * changes is how the page reads:
 * - One red action, "Save general settings", in the page header instead of a
 *   Save button per card. It sends the card(s) whose values changed, each
 *   with exactly the body that card's own Save sends with the switch off; with
 *   nothing changed it sends both, as pressing both buttons does today.
 * - Currency from the searchable list; decimals and the two Undo windows as
 *   steppers held to whole numbers inside today's ranges (0-6, 1-60), so a
 *   value the switch-off page would refuse cannot be entered.
 * - Someone who may read but not change the settings sees plain text and no
 *   red action.
 * - Saving ends with a done toast whose Undo writes the old values back (the
 *   same endpoint, the same bodies with the earlier values).
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { toast } from '@/lib/toast';
import { CURRENCY_OPTIONS } from '@/lib/money';
import { useCan } from '@/hooks/use-can';
import { emsService } from '@/services/ems-service';
import type { TenantSettings } from '@/types/ems';
import {
  Card,
  CardContent,
  CardHeader,
  CardHeading,
  CardTitle,
} from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { SearchSelect } from '@/components/platform/search-select';
import {
  useRegisterMainAction,
  type FxMainActionSpec,
} from '@/components/fx/actions/page-actions-context';
import { FxField, FxStepper } from '@/components/fx/fields';
import { FxPlainSetting, useFxUserName } from './fx-settings-bits';

/** The values the page edits, as the two switch-off cards hold them. */
export interface FxGeneralValues {
  defaultCurrency: string;
  priceDecimals: number;
  deferredDestructiveSeconds: number;
  deferredReversibleSeconds: number;
}

type CurrencyBody = Pick<TenantSettings, 'defaultCurrency' | 'priceDecimals'>;
type WindowsBody = Pick<
  TenantSettings,
  'deferredDestructiveSeconds' | 'deferredReversibleSeconds'
>;

/**
 * The PUT bodies one press of "Save general settings" sends, in order: the
 * currency card's body when it changed, the Undo windows card's body when
 * they changed, both when nothing changed. Each body is exactly what that
 * card's Save sends with the switch off.
 */
export function fxGeneralBodies(
  base: FxGeneralValues,
  values: FxGeneralValues,
): Array<CurrencyBody | WindowsBody> {
  const currency: CurrencyBody = {
    defaultCurrency: values.defaultCurrency,
    priceDecimals: values.priceDecimals,
  };
  const windows: WindowsBody = {
    deferredDestructiveSeconds: values.deferredDestructiveSeconds,
    deferredReversibleSeconds: values.deferredReversibleSeconds,
  };
  const currencyChanged =
    base.defaultCurrency !== values.defaultCurrency ||
    base.priceDecimals !== values.priceDecimals;
  const windowsChanged =
    base.deferredDestructiveSeconds !== values.deferredDestructiveSeconds ||
    base.deferredReversibleSeconds !== values.deferredReversibleSeconds;
  if (currencyChanged && !windowsChanged) return [currency];
  if (windowsChanged && !currencyChanged) return [windows];
  return [currency, windows];
}

/** The same keys of `values` as `body` has: the body that puts them back. */
function sameKeys<B extends object>(body: B, values: FxGeneralValues): B {
  const back = {} as Record<string, unknown>;
  for (const key of Object.keys(body)) back[key] = values[key as keyof FxGeneralValues];
  return back as B;
}

function fromSettings(s: TenantSettings): FxGeneralValues {
  return {
    defaultCurrency: s.defaultCurrency,
    priceDecimals: s.priceDecimals,
    deferredDestructiveSeconds: s.deferredDestructiveSeconds,
    deferredReversibleSeconds: s.deferredReversibleSeconds,
  };
}

export function FxGeneralSettings() {
  const { can } = useCan();
  const canManage = can('settings.update');
  const byWhom = useFxUserName();
  const [base, setBase] = useState<FxGeneralValues | null>(null);
  const [values, setValues] = useState<FxGeneralValues | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    emsService
      .getTenantSettings()
      .then((s) => {
        setBase(fromSettings(s));
        setValues(fromSettings(s));
      })
      .catch(() => undefined)
      .finally(() => setLoading(false));
  }, []);

  const set = <K extends keyof FxGeneralValues>(key: K, value: FxGeneralValues[K]) =>
    setValues((v) => (v ? { ...v, [key]: value } : v));

  const send = async (bodies: Array<CurrencyBody | WindowsBody>) => {
    let last: TenantSettings | null = null;
    for (const body of bodies) last = await emsService.setTenantSettings(body);
    return last;
  };

  const onSave = async () => {
    if (!base || !values) return;
    const bodies = fxGeneralBodies(base, values);
    const before = base;
    setSaving(true);
    try {
      const saved = await send(bodies);
      if (saved) {
        setBase(fromSettings(saved));
        setValues(fromSettings(saved));
      }
      toast.fxDone({
        what: 'General settings saved',
        byWhom,
        undo: () => {
          void send(bodies.map((b) => sameKeys(b, before)))
            .then((back) => {
              if (!back) return;
              setBase(fromSettings(back));
              setValues(fromSettings(back));
            })
            .catch(() => toast.error("Couldn't undo. The new settings stay."));
        },
      });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not save settings.');
    } finally {
      setSaving(false);
    }
  };

  const onSaveRef = useRef(onSave);
  onSaveRef.current = onSave;
  const ready = canManage && !loading && Boolean(values);
  const main = useMemo<FxMainActionSpec | null>(
    () =>
      ready
        ? {
            id: 'save-general',
            label: 'Save general settings',
            onClick: () => void onSaveRef.current(),
            working: saving,
          }
        : null,
    [ready, saving],
  );
  useRegisterMainAction(main);

  if (loading) {
    return (
      <div className="flex flex-col gap-5">
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }
  if (!values) {
    return (
      <Card>
        <CardContent className="py-6 text-sm text-(--fx-ink-2)">
          Couldn&apos;t load the settings.
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-5">
      <Card>
        <CardHeader>
          <CardHeading>
            <CardTitle>Default currency</CardTitle>
          </CardHeading>
        </CardHeader>
        <CardContent className="flex flex-col gap-5">
          {canManage ? (
            <>
              <FxField label="Currency" className="max-w-xs">
                <SearchSelect
                  ariaLabel="Currency"
                  value={values.defaultCurrency}
                  onChange={(v) => set('defaultCurrency', v || 'USD')}
                  options={CURRENCY_OPTIONS}
                />
              </FxField>
              <FxField label="Price decimal places" id="fx-price-decimals">
                <FxStepper
                  id="fx-price-decimals"
                  value={values.priceDecimals}
                  onChange={(n) => set('priceDecimals', n)}
                  min={0}
                  max={6}
                  step={1}
                  precision={0}
                />
              </FxField>
            </>
          ) : (
            <>
              <FxPlainSetting label="Currency">{values.defaultCurrency}</FxPlainSetting>
              <FxPlainSetting label="Price decimal places">
                {values.priceDecimals}
              </FxPlainSetting>
            </>
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardHeading>
            <CardTitle>Undo windows</CardTitle>
          </CardHeading>
        </CardHeader>
        <CardContent className="flex flex-col gap-5">
          {canManage ? (
            <>
              <FxField label="After a delete" id="fx-undo-delete">
                <FxStepper
                  id="fx-undo-delete"
                  value={values.deferredDestructiveSeconds}
                  onChange={(n) => set('deferredDestructiveSeconds', n)}
                  min={1}
                  max={60}
                  step={1}
                  precision={0}
                  unit="s"
                />
              </FxField>
              <FxField label="After other actions" id="fx-undo-other">
                <FxStepper
                  id="fx-undo-other"
                  value={values.deferredReversibleSeconds}
                  onChange={(n) => set('deferredReversibleSeconds', n)}
                  min={1}
                  max={60}
                  step={1}
                  precision={0}
                  unit="s"
                />
              </FxField>
            </>
          ) : (
            <>
              <FxPlainSetting label="After a delete">
                {values.deferredDestructiveSeconds} s
              </FxPlainSetting>
              <FxPlainSetting label="After other actions">
                {values.deferredReversibleSeconds} s
              </FxPlainSetting>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
