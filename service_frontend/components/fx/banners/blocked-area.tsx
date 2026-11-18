'use client';

/**
 * A blocked area says what it waits for, in place (gap audit, gap 7): when a
 * whole part of a page cannot be used yet (a reply box whose window has
 * closed, a page that needs a connection first), a thin strip in the `warn`
 * set sits at the top of that part, with one line saying what is missing and
 * the one way to fix it as a text button:
 *
 *   "No channel is connected to this workspace."  Connect channel
 *
 * It belongs to the page: never a system banner (those are about the whole
 * system) and never a toast. Rendered only by Foundryx UIUX page code.
 */
import type { ReactNode } from 'react';
import Link from 'next/link';
import { TriangleAlert } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import type { FxBannerAction } from './banner-store';

export interface FxBlockedAreaProps {
  /** What is missing and why, as one sentence. */
  children: ReactNode;
  /** The one way to fix it. */
  action?: FxBannerAction;
  className?: string;
}

export function FxBlockedArea({ children, action, className }: FxBlockedAreaProps) {
  return (
    <div
      role="status"
      data-fx-blocked-area=""
      className={cn(
        'flex flex-wrap items-center gap-x-3 gap-y-1 rounded-(--fx-r-m) bg-(--fx-warn-bg) px-3 py-1.5 text-sm text-(--fx-warn-ink)',
        className,
      )}
    >
      <span className="flex min-w-0 flex-1 basis-48 items-start gap-2">
        <TriangleAlert
          className="mt-0.5 size-4 shrink-0 opacity-70"
          aria-hidden="true"
        />
        <span className="min-w-0">{children}</span>
      </span>
      {action &&
        (action.href ? (
          <Button
            asChild
            variant="fx-text"
            size="sm"
            className="ms-auto text-current underline-offset-2 hover:underline"
          >
            <Link href={action.href}>{action.label}</Link>
          </Button>
        ) : (
          <Button
            variant="fx-text"
            size="sm"
            disabled={action.disabled}
            className="ms-auto text-current underline-offset-2 hover:underline"
            onClick={action.onClick}
          >
            {action.label}
          </Button>
        ))}
    </div>
  );
}
