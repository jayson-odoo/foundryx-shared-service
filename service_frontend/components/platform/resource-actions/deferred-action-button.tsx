'use client';

import { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { useReducedMotion } from '@/lib/motion';

export interface DeferredCountdownProps {
  /** Verb-first copy: "Deleting" reads as "Deleting in 10s". */
  verb: string;
  commitAt: string; // ISO Z
  windowSeconds: number;
  /** For a bulk park - "Deleting 12 users in 8s" (D13). */
  count?: number;
  noun?: string;
  onCancel: () => void;
  className?: string;
  // No `cancelling` prop (fix round 1 item 9): `useDeferredAction.cancel()`
  // now leaves `pending` SYNCHRONOUSLY on the caller's very next render, so
  // this whole countdown unmounts on the SAME click - there is never a
  // window where a stale/disabled Cancel button could be double-pressed
  // while a round trip is in flight. A prop that disables a button which no
  // longer exists by the time it would matter is dead weight, not a fix.
}

/** Treat a timezone-less ISO timestamp (shouldn't happen - the backend is
 * Z-suffixed - as a defensive net) as UTC. */
function asUtc(iso: string): string {
  return /[zZ]|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : `${iso}Z`;
}

/**
 * The countdown that REPLACES the confirmation dialog (D2, AC-DLA-44).
 *
 * The bar drains against the SERVER's `commitAt`, never a local counter, so
 * a refresh or a tab switch never restarts the window. There is no Escape
 * handler and no dialog - Cancel is the only way back, and it stays a
 * button (never a keyboard shortcut fires it, per the no-motion-on-a-
 * keyboard-action rule).
 */
export function DeferredCountdown({
  verb,
  commitAt,
  windowSeconds,
  count,
  noun,
  onCancel,
  className,
}: DeferredCountdownProps) {
  const target = Date.parse(asUtc(commitAt));
  const [now, setNow] = useState(() => Date.now());
  const prefersReducedMotion = useReducedMotion();

  useEffect(() => {
    // The fill itself doesn't need a fast tick (the CSS transition drains
    // it) - this only redraws the `role="timer"` label, so once a second is
    // plenty (AC-DLA-44).
    const tick = setInterval(() => setNow(Date.now()), 1000);
    const lapse = setTimeout(
      () => setNow(Math.max(Date.now(), target)),
      Math.max(0, target - Date.now()),
    );
    return () => {
      clearInterval(tick);
      clearTimeout(lapse);
    };
  }, [target]);

  // ONE linear transition, set ONCE via a double rAF (arms fresh on a new
  // target only - never re-arms on the 1s tick above, which is what makes
  // it "set once" rather than restarting every second).
  const [armed, setArmed] = useState<{ target: number; remainingMs: number } | null>(null);
  useEffect(() => {
    if (prefersReducedMotion) return;
    let second = 0;
    // Fix round 1 item 10: measure `remainingMs` INSIDE the second frame,
    // not from a timestamp captured before either frame runs. rAF is
    // throttled in a hidden/backgrounded tab, so a fixed pre-frame
    // measurement understates the elapsed time - the fill then arms a
    // near-full-duration transition against an already-mostly-elapsed
    // clock and visibly lags the server's real `commitAt`.
    const first = requestAnimationFrame(() => {
      second = requestAnimationFrame(() =>
        setArmed({ target, remainingMs: Math.max(0, target - Date.now()) }),
      );
    });
    return () => {
      cancelAnimationFrame(first);
      cancelAnimationFrame(second);
    };
  }, [target, prefersReducedMotion]);

  const remainingMs = Math.max(0, target - now);
  const windowMs = windowSeconds * 1000;
  const liveFraction = windowMs > 0 ? Math.max(0, Math.min(1, remainingMs / windowMs)) : 1;
  const lapsed = remainingMs <= 0;

  const fillStyle = prefersReducedMotion
    ? { transform: `scaleX(${liveFraction})` }
    : armed && armed.target === target
      ? {
          transform: 'scaleX(0)',
          transitionProperty: 'transform',
          transitionDuration: `${armed.remainingMs}ms`,
          transitionTimingFunction: 'linear',
        }
      : { transform: `scaleX(${liveFraction})` };

  const label = lapsed
    ? `${verb}…`
    : count && count > 1 && noun
      ? `${verb} ${count} ${noun} in ${Math.ceil(remainingMs / 1000)}s`
      : `${verb} in ${Math.ceil(remainingMs / 1000)}s`;

  return (
    <div
      data-testid="deferred-countdown"
      data-lapsed={lapsed ? 'true' : undefined}
      className={cn(
        'flex min-w-[13rem] flex-col gap-1.5 rounded-md border border-border bg-card px-3 py-2',
        className,
      )}
    >
      <div className="flex items-center gap-3">
        <span className="text-sm font-medium tabular-nums" role="timer">
          {label}
        </span>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="ms-auto h-7 px-2"
          onClick={() => {
            if (Date.now() >= target) return;
            onCancel();
          }}
          disabled={lapsed}
        >
          Cancel
        </Button>
      </div>
      <div className="h-1 overflow-hidden rounded-full bg-muted">
        <div
          data-testid="deferred-countdown-bar"
          className={cn(
            'h-full origin-left rounded-full transition-[background-color] duration-(--duration-fast) ease-(--ease-standard) motion-reduce:transition-none',
            lapsed ? 'bg-muted-foreground/40' : 'bg-destructive',
          )}
          // Fix round 1 item 8: hold the drained bar at `scaleX(0)` at
          // commit - snapping it back to `scaleX(1)` reads as the countdown
          // resetting/glitching at the exact moment the destructive action
          // fires, and a full bar visually says "100% complete" rather than
          // "committing". The track's colour swap (destructive -> muted)
          // animates instead, via the class transition above (no inline
          // `transitionProperty` fights it once `fillStyle` is no longer in
          // play at this branch).
          style={lapsed ? { transform: 'scaleX(0)' } : fillStyle}
        />
      </div>
    </div>
  );
}
