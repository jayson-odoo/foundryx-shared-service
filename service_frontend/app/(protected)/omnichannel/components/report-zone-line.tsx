'use client';

import { useFx } from '@/hooks/use-fx';
import { FxZoneLine } from '@/components/fx/fields';

/**
 * The zone the dashboard's and reports' days count in, under their page
 * header. Foundryx UIUX switch on: "Kuala Lumpur time (GMT+8)" (the quick
 * picks and day totals resolve in this zone); off: today's "Timezone: ..."
 * text, unchanged.
 */
export function ReportZoneLine({ timeZone }: { timeZone: string }) {
  const fx = useFx();
  if (fx) return <FxZoneLine timeZone={timeZone} className="m-0" />;
  return <>{`Timezone: ${timeZone}`}</>;
}
