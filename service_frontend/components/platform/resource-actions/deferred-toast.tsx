'use client';

import { toast } from 'sonner';
import { DeferredCountdown } from './deferred-action-button';

export interface DeferredToastInput {
  id: string;
  verb: string;
  commitAt: string; // ISO Z
  windowSeconds: number;
  count?: number;
  noun?: string;
  onCancel: () => void;
}

/**
 * The countdown for an action started from a LIST ROW or a bulk selection
 * (AC-DLA-45). A row has nowhere to put the countdown - the record page's
 * primary area doesn't exist here - so the affordance travels to a sonner
 * toast, and the row(s) dim via `data-pending` (D13, bulk dims every
 * selected row under ONE toast naming the count).
 */
export function deferredToast(input: DeferredToastInput): string | number {
  const { id, verb, commitAt, windowSeconds, count, noun, onCancel } = input;
  return toast.custom(
    () => (
      <DeferredCountdown
        verb={verb}
        commitAt={commitAt}
        windowSeconds={windowSeconds}
        count={count}
        noun={noun}
        onCancel={onCancel}
        className="w-full shadow-lg"
      />
    ),
    { id, duration: windowSeconds * 1000 + 8000 },
  );
}

export function dismissDeferredToast(id: string | number): void {
  toast.dismiss(id);
}
