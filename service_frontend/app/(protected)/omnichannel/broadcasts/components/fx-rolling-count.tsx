'use client';

/**
 * A count that rolls to its new value (Foundryx UIUX switch only; gap audit
 * "Lists and numbers that update by themselves": counts roll to the new
 * number in tabular figures over 0.35 s). Reduced motion: the value changes
 * at once. The first value shows as it is; only later changes roll.
 */
import { useEffect, useRef, useState } from 'react';
import { cn } from '@/lib/utils';

export const FX_ROLL_MS = 350;

/** Ease-out cubic, the playbook's ease-out curve closely enough for a number. */
export function rollStep(from: number, to: number, t: number): number {
  const k = Math.min(1, Math.max(0, t));
  const eased = 1 - (1 - k) ** 3;
  return Math.round(from + (to - from) * eased);
}

function reducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return true;
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

export function FxRollingCount({ value, className }: { value: number; className?: string }) {
  const [shown, setShown] = useState(value);
  const shownRef = useRef(value);

  useEffect(() => {
    const from = shownRef.current;
    if (from === value) return;
    if (reducedMotion() || typeof requestAnimationFrame !== 'function') {
      shownRef.current = value;
      setShown(value);
      return;
    }
    let frame = 0;
    const start = performance.now();
    const tick = (now: number) => {
      const next = rollStep(from, value, (now - start) / FX_ROLL_MS);
      shownRef.current = next;
      setShown(next);
      if (next !== value) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value]);

  return (
    <span className={cn('tabular-nums', className)}>
      {shown.toLocaleString('en-US')}
    </span>
  );
}
