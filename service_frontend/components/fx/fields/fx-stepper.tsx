'use client';

/**
 * Foundryx UIUX steppers (playbook 0.71.0 "Small counts" and "Steppers on a
 * value card"). Round − and + either side of the number; you can type it,
 * tap a button, hold it to keep counting, or use the arrow keys. − greys out
 * at the minimum and + at the maximum. Never browser up/down arrows.
 *
 * New for page waves: pages opt in by using them under `useFx()`.
 */
import { useEffect, useRef, useState } from 'react';
import { Minus, Plus } from 'lucide-react';
import { cn } from '@/lib/utils';
import { clampValue, decimalsOf, roundTo, snapToStep, stepValue } from '@/lib/fx/fields';
import { PRESSED_CLASS } from '@/components/ui/primitive-classes';
import { FX_FIELD_BOX } from './classes';
import { useFxControlName } from './fx-field-context';

/** Holding a button: first repeat after 400 ms, then every 80 ms. */
export const FX_HOLD_DELAY_MS = 400;
export const FX_HOLD_REPEAT_MS = 80;

export interface FxStepperProps {
  value: number;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  /** What − and + (and the arrow keys) add or take away. */
  step?: number;
  /** Also put a typed value on the step grid. Off by default: a typed value
   *  is only kept inside min and max (FX-12), so 6.5 stays 6.5 at step 1. */
  snap?: boolean;
  /** The most decimals the value may hold. Every value the field shows or
   *  sends is rounded to it, so a stored 6.510000228881836 reads 6.51 at
   *  precision 2. Without it, − and + keep the step's decimals and a typed
   *  value keeps what was typed. */
  precision?: number;
  /** Written after the number ("%", "days"). */
  unit?: string;
  disabled?: boolean;
  id?: string;
  'aria-label'?: string;
  'aria-labelledby'?: string;
  className?: string;
}

/** Press-and-hold repeat for a − or + button. */
function useHoldRepeat(run: () => boolean) {
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const runRef = useRef(run);
  runRef.current = run;
  const stop = () => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
  };
  useEffect(() => stop, []);
  const start = () => {
    stop();
    if (!runRef.current()) return;
    const tick = () => {
      if (!runRef.current()) return stop();
      timer.current = setTimeout(tick, FX_HOLD_REPEAT_MS);
    };
    timer.current = setTimeout(tick, FX_HOLD_DELAY_MS);
  };
  return { start, stop };
}

/**
 * The decimals − and + land on: the step's (and the grid start's), never
 * more than `precision`. A value between two steps moves onto the grid, so
 * 6.5 at step 1 goes to 7 and 6.
 */
export function fxStepperDecimals(step: number, min: number, precision?: number): number {
  const fromStep = Math.max(decimalsOf(step), Number.isFinite(min) ? decimalsOf(min) : 0);
  return precision === undefined ? fromStep : Math.min(fromStep, precision);
}

/** A number as the field holds it: rounded to `precision` when there is one. */
function clean(n: number, precision?: number): number {
  return precision === undefined ? n : roundTo(n, precision);
}

/** The stepper's number, its keys, and the hold-to-repeat buttons. */
function useStepper({ value: raw, onChange, min = -Infinity, max = Infinity, step = 1, snap = false, precision }: FxStepperProps) {
  // A value from the API may carry binary residue (a 32-bit 6.51 reads
  // 6.510000228881836): the field shows and steps it rounded to its
  // precision, and leaves the stored value alone until it is changed.
  const value = clean(raw, precision);
  const valueRef = useRef(value);
  valueRef.current = value;
  const [text, setText] = useState(String(value));
  const [typing, setTyping] = useState(false);
  useEffect(() => {
    if (!typing) setText(String(value));
  }, [value, typing]);

  const move = (direction: 1 | -1) => {
    const stepped = stepValue(valueRef.current, direction, min, max, step);
    // Every button, arrow-key and hold-to-repeat value is rounded to the
    // field's precision, so no residue (6.510000000000001) reaches onChange.
    const next = clampValue(roundTo(stepped, fxStepperDecimals(step, min, precision)), min, max);
    if (next === valueRef.current) return false;
    valueRef.current = next;
    onChange(next);
    return true;
  };
  const down = useHoldRepeat(() => move(-1));
  const up = useHoldRepeat(() => move(1));

  const commit = () => {
    setTyping(false);
    const n = Number(text.replace(/,/g, '').trim());
    if (text.trim() === '' || !Number.isFinite(n)) {
      setText(String(value));
      return;
    }
    const next = clean(snap ? snapToStep(n, min, max, step) : clampValue(n, min, max), precision);
    setText(String(next));
    if (next !== value) onChange(next);
  };

  const inputProps = {
    value: text,
    inputMode: 'decimal' as const,
    role: 'spinbutton',
    'aria-valuenow': value,
    'aria-valuemin': Number.isFinite(min) ? min : undefined,
    'aria-valuemax': Number.isFinite(max) ? max : undefined,
    onChange: (e: React.ChangeEvent<HTMLInputElement>) => {
      setTyping(true);
      setText(e.target.value);
    },
    onBlur: commit,
    onKeyDown: (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        move(1);
        setTyping(false);
      } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        move(-1);
        setTyping(false);
      } else if (e.key === 'Enter') {
        commit();
      }
    },
  };
  return { inputProps, down, up, atMin: value <= min, atMax: value >= max };
}

const ROUND =
  `${PRESSED_CLASS} inline-flex size-7 shrink-0 items-center justify-center rounded-full border border-(--fx-line-2) bg-(--fx-surface) text-(--fx-ink-2) ` +
  'hover:border-(--fx-ink-3) hover:text-(--fx-ink) disabled:pointer-events-none disabled:opacity-40 pointer-coarse:size-9';

/** Round − and + either side of the number. */
export function FxStepper(props: FxStepperProps) {
  const { disabled, unit, id, className } = props;
  const { inputProps, down, up, atMin, atMax } = useStepper(props);
  // Its own aria-label, else the labelled FxField around it, else the page's
  // `<label htmlFor={id}>`.
  const naming = useFxControlName({
    id,
    ariaLabel: props['aria-label'],
    ariaLabelledBy: props['aria-labelledby'],
  });
  return (
    <div className={cn('inline-flex items-center gap-2', className)} data-fx-stepper="">
      <button
        type="button"
        aria-label="Decrease"
        tabIndex={-1}
        disabled={disabled || atMin}
        onPointerDown={down.start}
        onPointerUp={down.stop}
        onPointerLeave={down.stop}
        onPointerCancel={down.stop}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') down.start();
        }}
        onKeyUp={down.stop}
        className={ROUND}
      >
        <Minus className="size-3.5" aria-hidden="true" />
      </button>
      <div className={cn(FX_FIELD_BOX, 'h-8.5 min-w-16 justify-center gap-1 px-2 text-[0.8125rem] pointer-coarse:text-base')}>
        <input
          type="text"
          autoComplete="off"
          disabled={disabled}
          {...naming}
          {...inputProps}
          className="w-12 min-w-0 bg-transparent text-center tabular-nums text-(--fx-ink) outline-none"
        />
        {unit && <span className="text-(--fx-ink-3)" aria-hidden="true">{unit}</span>}
      </div>
      <button
        type="button"
        aria-label="Increase"
        tabIndex={-1}
        disabled={disabled || atMax}
        onPointerDown={up.start}
        onPointerUp={up.stop}
        onPointerLeave={up.stop}
        onPointerCancel={up.stop}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') up.start();
        }}
        onKeyUp={up.stop}
        className={ROUND}
      >
        <Plus className="size-3.5" aria-hidden="true" />
      </button>
    </div>
  );
}

/**
 * A value card that is itself the stepper: the left 27.5% is −, the right
 * 27.5% is +, and the middle lets you type. On phones − and + sit below the
 * value instead, side by side, keeping the same share of the card's width.
 */
export function FxValueCardStepper(props: FxStepperProps & { label: string }) {
  const { disabled, unit, id, className, label } = props;
  const { inputProps, down, up, atMin, atMax } = useStepper(props);
  const zone =
    'flex items-center justify-center text-(--fx-ink-2) hover:bg-(--fx-surface-2) hover:text-(--fx-ink) disabled:pointer-events-none disabled:opacity-40';
  const hold = (h: { start: () => void; stop: () => void }) => ({
    onPointerDown: h.start,
    onPointerUp: h.stop,
    onPointerLeave: h.stop,
    onPointerCancel: h.stop,
  });
  return (
    <div
      data-fx-value-card=""
      className={cn(
        'grid overflow-hidden rounded-(--fx-r-l) border border-(--fx-line) bg-(--fx-surface) text-(--fx-ink)',
        'grid-cols-[27.5%_1fr_27.5%]',
        className,
      )}
    >
      <button
        type="button"
        aria-label={`Decrease ${label}`}
        tabIndex={-1}
        disabled={disabled || atMin}
        {...hold(down)}
        className={cn(PRESSED_CLASS, zone, 'col-start-1 row-start-2 h-9 border-t border-e border-(--fx-line) sm:row-start-1 sm:h-auto sm:border-t-0 sm:border-e-0')}
      >
        <Minus className="size-4" aria-hidden="true" />
      </button>
      <label className="col-span-3 col-start-1 row-start-1 flex flex-col items-center justify-center gap-0.5 px-2 py-1.5 sm:col-span-1 sm:col-start-2">
        <span className="text-xs text-(--fx-ink-3)">{label}</span>
        <span className="flex items-baseline gap-1">
          <input
            id={id}
            type="text"
            autoComplete="off"
            disabled={disabled}
            {...inputProps}
            className="w-16 min-w-0 bg-transparent text-center text-lg font-semibold tabular-nums outline-none focus-visible:rounded-(--fx-r-s) focus-visible:ring-2 focus-visible:ring-(--fx-link)"
          />
          {unit && <span className="text-sm text-(--fx-ink-3)" aria-hidden="true">{unit}</span>}
        </span>
      </label>
      <button
        type="button"
        aria-label={`Increase ${label}`}
        tabIndex={-1}
        disabled={disabled || atMax}
        {...hold(up)}
        className={cn(PRESSED_CLASS, zone, 'col-start-3 row-start-2 h-9 border-t border-s border-(--fx-line) sm:row-start-1 sm:h-auto sm:border-t-0 sm:border-s-0')}
      >
        <Plus className="size-4" aria-hidden="true" />
      </button>
    </div>
  );
}
