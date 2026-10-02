'use client';

import { LoaderCircleIcon } from 'lucide-react';
import { toAbsoluteUrl } from '@/lib/helpers';

/**
 * The full-screen auth-gate loader (AC-DLA-49) - a spinner, no loading-word
 * text label (banned repo-wide as UI copy; the spin itself communicates
 * "in progress").
 */
export function ScreenLoader() {
  return (
    <div
      role="status"
      aria-label="Loading"
      className="flex flex-col items-center gap-3 justify-center fixed inset-0 z-50"
    >
      <img
        className="h-[30px] max-w-none"
        src={toAbsoluteUrl('/media/app/mini-logo.svg')}
        alt="logo"
      />
      <LoaderCircleIcon className="size-5 animate-spin text-muted-foreground" />
    </div>
  );
}
