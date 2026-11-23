'use client';

/**
 * Undo by waiting, under the Foundryx UIUX switch (gap audit rule 4 as SS
 * applies it, playbook-uiux.md): the action is held on the server for the
 * tenant's window (10 s deletes, 5 s otherwise, from Settings > General),
 * shown as "Deleting 12 contacts in 8 s" with an "Undo" button and a bar
 * draining against the server's `commitAt`. Unlike the done toast it never
 * pauses under the pointer: the server's clock does not stop. The done
 * message after it ("12 contacts deleted.") is unchanged.
 */
import { useEffect, useState, type CSSProperties } from 'react';
import { cn } from '@/lib/utils';
import { useReducedMotion } from '@/lib/motion';
import type { DeferredCountdownProps } from '@/components/platform/resource-actions/deferred-action-button';

function asUtc(iso: string): string {
  return /[zZ]|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : `${iso}Z`;
}

/** "Deleting 12 contacts in 8 s" / "Deleting Barcode scanner in 8 s" /
 *  "Deleting in 8 s" / "Deleting" (pure). */
export function fxCountdownLabel(
  verb: string,
  remainingMs: number,
  count?: number,
  noun?: string,
  name?: string,
): string {
  if (remainingMs <= 0) return `${verb}…`;
  const secs = Math.ceil(remainingMs / 1000);
  if (count && count > 1 && noun) return `${verb} ${count} ${noun} in ${secs} s`;
  const what = name?.trim();
  return what ? `${verb} ${what} in ${secs} s` : `${verb} in ${secs} s`;
}

export function FxDeferredCountdown({
  verb,
  commitAt,
  windowSeconds,
  count,
  noun,
  fxName,
  onCancel,
  className,
  fxSurface,
}: DeferredCountdownProps) {
  const target = Date.parse(asUtc(commitAt));
  const [now, setNow] = useState(() => Date.now());
  const reduced = useReducedMotion();

  useEffect(() => {
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

  const [armed, setArmed] = useState<{ target: number; ms: number } | null>(
    null,
  );
  useEffect(() => {
    if (reduced) return;
    let second = 0;
    const first = requestAnimationFrame(() => {
      second = requestAnimationFrame(() =>
        setArmed({ target, ms: Math.max(0, target - Date.now()) }),
      );
    });
    return () => {
      cancelAnimationFrame(first);
      cancelAnimationFrame(second);
    };
  }, [target, reduced]);

  const remainingMs = Math.max(0, target - now);
  const windowMs = windowSeconds * 1000;
  const fraction =
    windowMs > 0 ? Math.max(0, Math.min(1, remainingMs / windowMs)) : 1;
  const lapsed = remainingMs <= 0;
  const barStyle: CSSProperties = lapsed
    ? { transform: 'scaleX(0)' }
    : !reduced && armed && armed.target === target
      ? {
          transform: 'scaleX(0)',
          transitionProperty: 'transform',
          transitionDuration: `${armed.ms}ms`,
          transitionTimingFunction: 'linear',
        }
      : { transform: `scaleX(${fraction})` };

  const toast = fxSurface === 'toast';

  return (
    <div
      data-testid="deferred-countdown"
      data-lapsed={lapsed ? 'true' : undefined}
      data-fx-countdown=""
      className={cn(
        'flex min-w-[13rem] flex-col overflow-hidden rounded-(--fx-r-l)',
        toast
          ? 'w-[min(360px,calc(100vw-32px))] bg-(--fx-toast-bg) text-(--fx-toast-ink) shadow-[0_8px_24px_var(--fx-lift)]'
          : 'border border-(--fx-line) bg-(--fx-surface) text-(--fx-ink)',
        !toast && className,
      )}
    >
      <div className="flex items-center gap-3 py-1.5 ps-4 pe-2 text-sm">
        <span className="min-w-0 flex-1 font-semibold tabular-nums" role="timer">
          {fxCountdownLabel(verb, remainingMs, count, noun, fxName)}
        </span>
        <button
          type="button"
          disabled={lapsed}
          onClick={() => {
            if (Date.now() >= target) return;
            onCancel();
          }}
          className={cn(
            'min-h-11 shrink-0 cursor-pointer px-3 font-bold transition-[translate,transform,scale,opacity] duration-(--fx-t-hover) ease-(--fx-ease-out) hover:-translate-y-0.5 active:scale-[0.97] disabled:cursor-default disabled:opacity-45 motion-reduce:active:scale-100',
            toast ? 'text-(--fx-toast-link)' : 'text-(--fx-link)',
          )}
        >
          Undo
        </button>
      </div>
      <div
        data-testid="deferred-countdown-bar"
        className={cn(
          'h-[3px] origin-left',
          lapsed
            ? 'bg-current opacity-30'
            : toast
              ? 'bg-(--fx-toast-link)'
              : 'bg-(--fx-act)',
        )}
        style={barStyle}
      />
    </div>
  );
}
