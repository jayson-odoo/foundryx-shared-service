'use client';

/**
 * Reading the Foundryx UIUX switch from a component (playbook-uiux.md).
 *
 * A shared component opts in with one branch above its legacy body:
 *
 *   export function Thing(props: ThingProps) {
 *     return useFx() ? <FxThing {...props} /> : <ThingLegacy {...props} />;
 *   }
 *
 * The legacy body is renamed, never edited, so the off markup stays identical.
 * Both hooks return "off" with no provider and inside `<FxOff>`.
 */
import { useContext } from 'react';
import { fxSettingValue } from '@/lib/fx/settings-schema';
import { FxContext, type FxContextValue } from '@/providers/fx-provider';
import { FxOffContext } from '@/components/fx/fx-off';

/** True while the Foundryx UIUX switch is on for this browser. */
export function useFx(): boolean {
  const ctx = useContext(FxContext);
  const forcedOff = useContext(FxOffContext);
  return Boolean(ctx?.on) && !forcedOff;
}

/**
 * An Advanced setting's effective value while the switch is on (stored, else
 * the playbook default), or undefined while it is off or for an unknown key.
 */
export function useFxSetting(key: string): boolean | number | undefined {
  const ctx = useContext(FxContext);
  const forcedOff = useContext(FxOffContext);
  if (!ctx?.on || forcedOff) return undefined;
  return fxSettingValue(ctx.settings, key);
}

/**
 * The full switch state, for the Theme panel and Advanced settings. Null
 * outside the provider and inside `<FxOff>` (those places show no switch).
 */
export function useFxControls(): FxContextValue | null {
  const ctx = useContext(FxContext);
  const forcedOff = useContext(FxOffContext);
  return forcedOff ? null : ctx;
}
