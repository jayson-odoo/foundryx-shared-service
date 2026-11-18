'use client';

import { LoaderCircleIcon } from 'lucide-react';
import { AppLogo } from '@/components/platform/branding/app-logo';
import { useTenantBranding } from '@/hooks/use-branding';

/**
 * The full-screen auth-gate loader (AC-DLA-49) - a spinner, no loading-word
 * text label (banned repo-wide as UI copy; the spin itself communicates
 * "in progress").
 */
export function ScreenLoader() {
  const { branding } = useTenantBranding();
  return (
    <div
      role="status"
      aria-label="Loading"
      className="flex flex-col items-center gap-3 justify-center fixed inset-0 z-50"
    >
      <AppLogo branding={branding} variant="mini" />
      <LoaderCircleIcon className="size-5 animate-spin text-muted-foreground" />
    </div>
  );
}
