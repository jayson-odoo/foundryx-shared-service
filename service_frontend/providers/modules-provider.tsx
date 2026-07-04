'use client';

import { ReactNode } from 'react';

/**
 * App-wide module providers wrapper.
 *
 * The Metronic store-client demo context was removed with the EMS-domain strip
 * (shared-service fork). This is a pass-through today; installable services that
 * need an app-level provider hook in here.
 */
export function ModulesProvider({ children }: { children: ReactNode }) {
  return <>{children}</>;
}
