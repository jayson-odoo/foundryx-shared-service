'use client';

import { ChevronLeft, ChevronRight } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useRecordNav, type UseRecordNavOptions } from '@/hooks/use-record-nav';

export type RecordNavProps = UseRecordNavOptions & {
  /**
   * Wraps a navigation action behind the form's dirty-guard: runs it now when
   * clean, else defers it behind the Discard-changes dialog (async - no
   * synchronous boolean, so the prompt is a real dialog not window.confirm).
   */
  guard?: (proceed: () => void) => void;
};

/** The circular "‹ 1 / N ›" record pager shown top-right of a form (plan 02 §3b). */
export function RecordNav({ guard, ...options }: RecordNavProps) {
  const nav = useRecordNav(options);
  if (!nav.available) return null;

  const attempt = (fn: () => void) => {
    if (guard) guard(fn);
    else fn();
  };

  return (
    <div className="flex items-center gap-1 rounded-md border border-border p-0.5">
      <Button
        variant="ghost"
        size="sm"
        mode="icon"
        className="size-7"
        disabled={nav.isNavigating}
        onClick={() => attempt(nav.goPrev)}
        aria-label="Previous record"
      >
        <ChevronLeft />
      </Button>
      <span className="px-1.5 text-xs font-medium tabular-nums text-muted-foreground">
        {nav.label}
      </span>
      <Button
        variant="ghost"
        size="sm"
        mode="icon"
        className="size-7"
        disabled={nav.isNavigating}
        onClick={() => attempt(nav.goNext)}
        aria-label="Next record"
      >
        <ChevronRight />
      </Button>
    </div>
  );
}
