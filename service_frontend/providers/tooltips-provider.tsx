'use client';

import { ReactNode } from 'react';
import { TooltipProvider } from '@/components/ui/tooltip';
import { useFxSetting } from '@/hooks/use-fx';

/**
 * The ONE `TooltipProvider` for the whole app (AC-DLA-16). 700ms before a
 * tooltip appears reads as deliberate, not accidental hover noise; once one
 * tooltip has shown, `skipDelayDuration` lets the next 300ms of hovering
 * around the same area skip the wait.
 *
 * Foundryx UIUX switch on (playbook-uiux.md): the playbook's tooltip delay
 * (setting "Tooltip delay", 0.3 s) instead. Both branches render the same
 * component in the same place, so flipping the switch never remounts the app
 * this provider wraps.
 */
export function TooltipsProvider({ children }: { children: ReactNode }) {
  // Undefined while the switch is off.
  const fxDelay = useFxSetting('tip-delay');
  return typeof fxDelay === 'number' ? (
    <TooltipProvider delayDuration={fxDelay * 1000} skipDelayDuration={300}>
      {children}
    </TooltipProvider>
  ) : (
    <TooltipProvider delayDuration={700} skipDelayDuration={300}>
      {children}
    </TooltipProvider>
  );
}
