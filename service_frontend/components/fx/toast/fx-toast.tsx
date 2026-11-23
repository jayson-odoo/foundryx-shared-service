'use client';

/**
 * The done toast under the Foundryx UIUX switch (playbook 0.71.0 "When
 * something is done"): says what happened, for whom, how many and by whom;
 * Undo where it can be reversed; closes after 6 s (setting "How long toasts
 * stay") with a bar showing the time left, and pauses while the pointer is on
 * it. Never "Success!". Shown through `toast.fxDone` in lib/toast.ts.
 */
import { useEffect, useRef, useState, type CSSProperties } from 'react';
import { useFxSetting } from '@/hooks/use-fx';

export interface FxDoneInput {
  /** What happened, as a sentence head: "Lim Wei Jie assigned to Kay". */
  what: string;
  /** For whom, when it is not already in `what`. */
  forWhom?: string;
  /** How many or how much, when it is not already in `what`. */
  howMany?: string;
  /** Who did it: shown as "by Kay". */
  byWhom?: string;
  /** Reverses the action; shows the Undo button. */
  undo?: () => void;
  /** Overrides the setting, in seconds. */
  seconds?: number;
}

/** The second line: for whom, how many, by whom (pure, tested). */
export function fxDoneDetail(input: FxDoneInput): string {
  return [input.forWhom, input.howMany, input.byWhom && `by ${input.byWhom}`]
    .filter(Boolean)
    .join(', ');
}

interface FxToastProps extends FxDoneInput {
  onClose: () => void;
}

export function FxToast({ onClose, undo, seconds, ...input }: FxToastProps) {
  const setting = useFxSetting('toast-time');
  const totalMs =
    (seconds ?? (typeof setting === 'number' ? setting : 6)) * 1000;
  // Time left is kept as "remaining at `since`"; while paused, `since` is null.
  const [left, setLeft] = useState(totalMs);
  const [running, setRunning] = useState(true);
  const since = useRef<number | null>(Date.now());
  const closed = useRef(false);

  const close = () => {
    if (closed.current) return;
    closed.current = true;
    onClose();
  };

  useEffect(() => {
    if (!running) return;
    since.current = Date.now();
    const t = setTimeout(close, left);
    return () => clearTimeout(t);
    // `left` only changes on pause, which stops this timer first.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running]);

  const pause = () => {
    if (!running || since.current === null) return;
    const elapsed = Date.now() - since.current;
    setLeft((current) => Math.max(0, current - elapsed));
    since.current = null;
    setRunning(false);
  };

  // Double frame so the bar starts from its current width, then drains.
  const [armed, setArmed] = useState(false);
  useEffect(() => {
    if (!running) {
      setArmed(false);
      return;
    }
    let second = 0;
    const first = requestAnimationFrame(() => {
      second = requestAnimationFrame(() => setArmed(true));
    });
    return () => {
      cancelAnimationFrame(first);
      cancelAnimationFrame(second);
    };
  }, [running]);

  const fraction = totalMs > 0 ? left / totalMs : 0;
  const barStyle: CSSProperties =
    running && armed
      ? {
          transform: 'scaleX(0)',
          transitionProperty: 'transform',
          transitionDuration: `${left}ms`,
          transitionTimingFunction: 'linear',
        }
      : { transform: `scaleX(${fraction})` };

  const detail = fxDoneDetail(input);

  return (
    <div
      role="status"
      data-fx-toast=""
      data-paused={running ? undefined : ''}
      onPointerEnter={pause}
      onPointerLeave={() => setRunning(true)}
      className="w-[min(360px,calc(100vw-32px))] overflow-hidden rounded-(--fx-r-l) bg-(--fx-toast-bg) text-(--fx-toast-ink) shadow-[0_8px_24px_var(--fx-lift)]"
    >
      <div className="flex items-center gap-3 py-2.5 ps-4 pe-2.5 text-sm">
        <span className="min-w-0 flex-1">
          <b className="font-semibold">{input.what}</b>
          {detail && (
            <small className="block text-[0.8125rem] opacity-80">{detail}</small>
          )}
        </span>
        {undo && (
          <button
            type="button"
            className="min-h-11 shrink-0 cursor-pointer px-3 font-bold text-(--fx-toast-link) transition-[translate,transform,scale] duration-(--fx-t-hover) ease-(--fx-ease-out) hover:-translate-y-0.5 active:scale-[0.97] motion-reduce:active:scale-100"
            onClick={() => {
              undo();
              close();
            }}
          >
            Undo
          </button>
        )}
      </div>
      <div
        data-fx-toast-bar=""
        className="h-[3px] origin-left bg-(--fx-toast-link)"
        style={barStyle}
      />
    </div>
  );
}
