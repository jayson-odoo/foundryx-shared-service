'use client';

/**
 * The Foundryx UIUX slider (playbook 0.71.0 "Sliders"): a 4px rounded track
 * in `--fx-line-2`, filled in the link colour up to a 22px round thumb with a
 * 2px link ring that grows a little on hover (x1.08) and while dragged
 * (x1.2). The steps show as dots only while the pointer or keyboard focus is
 * on the slider, and the dot nearest the pointer grows. Press and drag moves
 * the thumb freely; on release it snaps to the nearest step, gliding there,
 * so the value is always a step's value. Arrow keys, Home and End work as
 * before. `Slider` / `SliderThumb` render these while the switch is on.
 */
import * as React from 'react';
import { Slider as SliderPrimitive } from 'radix-ui';
import { cn } from '@/lib/utils';
import { snapToStep } from '@/lib/fx/fields';

/** More dots than this would sit too close together; long sliders show none. */
const MAX_DOTS = 30;
/** While dragging, the thumb moves in this many sub-steps per step. */
const FREE = 20;

type RootProps = React.ComponentProps<typeof SliderPrimitive.Root>;

export function FxSlider({
  className,
  children,
  min = 0,
  max = 100,
  step = 1,
  value,
  defaultValue,
  onValueChange,
  onValueCommit,
  onPointerDown,
  onPointerMove,
  onPointerLeave,
  ...props
}: RootProps) {
  const [inner, setInner] = React.useState<number[]>(defaultValue ?? [min]);
  const [drag, setDrag] = React.useState<number[] | null>(null);
  const [near, setNear] = React.useState<number | null>(null);
  const rootRef = React.useRef<HTMLSpanElement>(null);
  const settled = value ?? inner;
  const snap = (v: number[]) => v.map((n) => snapToStep(n, min, max, step));
  const count = Math.round((max - min) / step);
  const dots = count > 0 && count <= MAX_DOTS ? Array.from({ length: count + 1 }, (_, i) => i) : [];

  const nearest = (clientX: number) => {
    const rect = rootRef.current?.getBoundingClientRect();
    if (!rect || rect.width === 0 || !dots.length) return null;
    const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
    return Math.round(ratio * count);
  };

  return (
    <SliderPrimitive.Root
      ref={rootRef}
      data-slot="slider"
      data-fx-slider=""
      data-dragging={drag ? '' : undefined}
      min={min}
      max={max}
      step={drag ? step / FREE : step}
      value={drag ?? settled}
      onPointerDown={(e) => {
        setDrag(settled);
        onPointerDown?.(e);
      }}
      onPointerMove={(e) => {
        setNear(nearest(e.clientX));
        onPointerMove?.(e);
      }}
      onPointerLeave={(e) => {
        setNear(null);
        onPointerLeave?.(e);
      }}
      onValueChange={(next) => {
        if (drag) {
          setDrag(next);
          const snapped = snap(next);
          if (snapped.some((n, i) => n !== (settled[i] ?? n))) {
            if (value === undefined) setInner(snapped);
            onValueChange?.(snapped);
          }
          return;
        }
        if (value === undefined) setInner(next);
        onValueChange?.(next);
      }}
      onValueCommit={(next) => {
        const snapped = snap(next);
        setDrag(null);
        if (value === undefined) setInner(snapped);
        onValueChange?.(snapped);
        onValueCommit?.(snapped);
      }}
      className={cn(
        'group/fx-slider relative flex h-6 w-full touch-none select-none items-center',
        // Glide to the step on release; follow the pointer exactly while dragging.
        'not-data-dragging:[&_[data-fx-slider-glide]]:transition-[left,right] not-data-dragging:[&_[data-fx-slider-glide]]:duration-(--fx-t-toggle)',
        'not-data-dragging:[&>span:has(>[role=slider])]:transition-[left] not-data-dragging:[&>span:has(>[role=slider])]:duration-(--fx-t-toggle)',
        className,
      )}
      {...props}
    >
      <SliderPrimitive.Track className="relative h-1 w-full grow rounded-(--fx-r-pill) bg-(--fx-line-2)">
        <SliderPrimitive.Range data-fx-slider-glide="" className="absolute h-full rounded-(--fx-r-pill) bg-(--fx-link)" />
      </SliderPrimitive.Track>
      {dots.length > 0 && (
        <span aria-hidden="true" className="pointer-events-none absolute inset-x-[11px] top-1/2 h-0">
          {dots.map((i) => (
            <span
              key={i}
              className={cn(
                'absolute top-0 size-1 -translate-x-1/2 -translate-y-1/2 rounded-full bg-(--fx-ink-3) opacity-0',
                'transition-[opacity,scale] duration-(--fx-t-hover) group-hover/fx-slider:opacity-70 group-focus-within/fx-slider:opacity-70',
                near === i && 'scale-[1.8] opacity-100',
              )}
              style={{ left: `${(i / count) * 100}%` }}
            />
          ))}
        </span>
      )}
      {children}
    </SliderPrimitive.Root>
  );
}

export function FxSliderThumb({ className, ...props }: React.ComponentProps<typeof SliderPrimitive.Thumb>) {
  return (
    <SliderPrimitive.Thumb
      data-slot="slider-thumb"
      className={cn(
        'block size-[22px] shrink-0 cursor-grab rounded-full border-2 border-(--fx-link) bg-(--fx-surface) shadow-[0_1px_4px_var(--fx-lift)] outline-none',
        'transition-[scale,box-shadow] duration-(--fx-t-hover) ease-(--fx-ease-out) hover:scale-[1.08]',
        'group-data-dragging/fx-slider:scale-[1.2] group-data-dragging/fx-slider:cursor-grabbing',
        'focus-visible:ring-4 focus-visible:ring-(--fx-link)/25',
        className,
      )}
      {...props}
    />
  );
}
