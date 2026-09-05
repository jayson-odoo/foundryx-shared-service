'use client';

import { ReactNode } from 'react';
import { TooltipProvider } from '@/components/ui/tooltip';

/**
 * The ONE `TooltipProvider` for the whole app (AC-DLA-16). 700ms before a
 * tooltip appears reads as deliberate, not accidental hover noise; once one
 * tooltip has shown, `skipDelayDuration` lets the next 300ms of hovering
 * around the same area skip the wait.
 */
export function TooltipsProvider({ children }: { children: ReactNode }) {
  return (
    <TooltipProvider delayDuration={700} skipDelayDuration={300}>
      {children}
    </TooltipProvider>
  );
}
