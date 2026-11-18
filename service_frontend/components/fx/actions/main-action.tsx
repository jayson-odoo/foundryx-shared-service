'use client';

/**
 * The red action (playbook 0.71.0 "Actions": the one Main Action per page).
 *
 * - Foundryx red pill with a round white arrow dot; a light follows the
 *   pointer, the button leans toward it (setting "The red action's lean") and
 *   the arrow turns on hover.
 * - Short label at rest; on hover or keyboard focus it widens to the left and
 *   shows the full action ("Record RM 2,500.00 from Client E"). Touch screens
 *   keep the short label (no hover). Screen readers always get the full label.
 * - Blocked: greyed, its reason right-aligned under it in light red, and
 *   pointing at or clicking it pulses the thing it waits for.
 * - Working: a spinner replaces the arrow; the label and width stay and a
 *   second press does nothing.
 *
 * Rendered only while the Foundryx UIUX switch is on.
 */
import {
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent,
} from 'react';
import { ArrowRight, LoaderCircle } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useFxSetting } from '@/hooks/use-fx';
import { Button } from '@/components/ui/button';
import type { FxMainActionSpec } from './page-actions-context';
import { pulseFxTarget } from './pulse';

export interface FxMainActionProps extends Omit<FxMainActionSpec, 'id'> {
  id?: string;
  /** `submit` for a dialog's or form's own red action. */
  type?: 'button' | 'submit';
  className?: string;
}

const LEAN_PX = 4;

export function FxMainAction({
  label,
  fullLabel,
  onClick,
  form,
  blocked,
  working,
  type = 'button',
  className,
}: FxMainActionProps) {
  const reasonId = useId();
  const lean = useFxSetting('lean') !== false;
  const full = fullLabel && fullLabel !== label ? fullLabel : undefined;
  const l0 = useRef<HTMLSpanElement>(null);
  const l1 = useRef<HTMLSpanElement>(null);
  const [widths, setWidths] = useState<{ w0: number; w1: number } | null>(null);
  const [pointer, setPointer] = useState<{
    mx: number;
    my: number;
    dx: number;
    dy: number;
  } | null>(null);
  const pulsedOnEnter = useRef(false);

  // The label slot animates between the two measured widths; with nothing to
  // measure (no full label, or no layout) it stays at its natural width.
  useLayoutEffect(() => {
    if (!full || !l0.current || !l1.current) {
      setWidths(null);
      return;
    }
    const w0 = l0.current.offsetWidth;
    const w1 = l1.current.offsetWidth;
    setWidths(w0 && w1 ? { w0, w1 } : null);
  }, [label, full]);

  const pulse = () => {
    if (blocked?.pulseTarget) pulseFxTarget(blocked.pulseTarget);
  };

  const onPointerMove = (event: PointerEvent<HTMLButtonElement>) => {
    if (event.pointerType !== 'mouse' || blocked) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    const towards = (offset: number, size: number) =>
      size ? ((offset - size / 2) / (size / 2)) * LEAN_PX : 0;
    setPointer({
      mx: x,
      my: y,
      dx: lean ? towards(x, rect.width) : 0,
      dy: lean ? towards(y, rect.height) : 0,
    });
  };

  const style = {
    '--fx-mx': pointer ? `${pointer.mx}px` : '50%',
    '--fx-my': pointer ? `${pointer.my}px` : '50%',
    transform: pointer
      ? `translate(${pointer.dx.toFixed(2)}px, ${pointer.dy.toFixed(2)}px)`
      : undefined,
  } as CSSProperties;

  const reveal = full && !blocked;

  return (
    <div
      data-fx-main-action=""
      className={cn('relative flex flex-col items-end', className)}
    >
      <Button
        type={type}
        form={form}
        variant="fx-main"
        aria-label={full ?? label}
        aria-disabled={blocked ? true : undefined}
        aria-describedby={blocked ? reasonId : undefined}
        aria-busy={working ? true : undefined}
        style={style}
        className={cn(
          'group/act h-auto min-h-12 rounded-(--fx-r-pill) gap-3 ps-5 pe-2 text-base transition-[transform,scale,box-shadow] duration-(--fx-t-layout) ease-(--fx-ease-out)',
          !blocked &&
            'hover:bg-[image:radial-gradient(circle_70px_at_var(--fx-mx)_var(--fx-my),rgba(255,255,255,0.5),rgba(255,255,255,0.12)_45%,rgba(255,255,255,0)_75%)] focus-visible:bg-[image:radial-gradient(circle_70px_at_50%_50%,rgba(255,255,255,0.4),rgba(255,255,255,0)_75%)]',
          working && 'pointer-events-none',
        )}
        onPointerEnter={() => {
          if (blocked && !pulsedOnEnter.current) {
            pulsedOnEnter.current = true;
            pulse();
          }
        }}
        onPointerMove={onPointerMove}
        onPointerLeave={() => {
          pulsedOnEnter.current = false;
          setPointer(null);
        }}
        onClick={(event) => {
          if (blocked) {
            event.preventDefault();
            pulse();
            return;
          }
          if (working) {
            event.preventDefault();
            return;
          }
          onClick?.();
        }}
      >
        <span
          data-fx-decor=""
          className={cn(
            'relative inline-block h-[1.5em] overflow-hidden whitespace-nowrap leading-normal tabular-nums',
            widths &&
              'w-(--fx-w0) transition-[width] duration-(--fx-t-open) ease-(--fx-ease-out)',
            widths &&
              reveal &&
              'group-hover/act:w-(--fx-w1) group-focus-visible/act:w-(--fx-w1)',
          )}
          style={
            widths
              ? ({
                  '--fx-w0': `${widths.w0}px`,
                  '--fx-w1': `${widths.w1}px`,
                } as CSSProperties)
              : undefined
          }
        >
          <span
            ref={l0}
            data-fx-decor=""
            className={cn(
              'inline-block transition-[translate,opacity] duration-(--fx-t-open) ease-(--fx-ease-out)',
              reveal &&
                'group-hover/act:-translate-y-[70%] group-hover/act:opacity-0 group-focus-visible/act:-translate-y-[70%] group-focus-visible/act:opacity-0',
            )}
          >
            {label}
          </span>
          {full && (
            <span
              ref={l1}
              aria-hidden="true"
              data-fx-decor=""
              className={cn(
                'absolute start-0 top-0 inline-block translate-y-[70%] opacity-0 transition-[translate,opacity] duration-(--fx-t-open) ease-(--fx-ease-out)',
                reveal &&
                  'group-hover/act:translate-y-0 group-hover/act:opacity-100 group-focus-visible/act:translate-y-0 group-focus-visible/act:opacity-100',
              )}
            >
              {full}
            </span>
          )}
        </span>
        <span className="grid size-8 shrink-0 place-items-center rounded-full bg-white text-(--fx-act)">
          {working ? (
            <LoaderCircle
              aria-hidden="true"
              className="size-4 animate-spin"
              strokeWidth={2.5}
            />
          ) : (
            <ArrowRight
              aria-hidden="true"
              className={cn(
                'size-4 transition-transform duration-(--fx-t-layout) ease-(--fx-ease-out)',
                !blocked &&
                  'group-hover/act:-rotate-45 group-focus-visible/act:-rotate-45',
              )}
              strokeWidth={2.5}
            />
          )}
        </span>
      </Button>
      {blocked && (
        <p
          id={reasonId}
          className="pointer-events-none absolute end-0 top-full mt-1 w-max max-w-64 text-end text-sm font-semibold text-[color-mix(in_srgb,var(--fx-act)_82%,var(--fx-surface))] max-sm:static max-sm:max-w-56"
        >
          {blocked.reason}
        </p>
      )}
    </div>
  );
}
