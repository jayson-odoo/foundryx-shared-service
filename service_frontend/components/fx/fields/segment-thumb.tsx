'use client';

/**
 * The sliding thumb of a Foundryx UIUX segmented toggle (playbook 0.71.0
 * "Toggles"): it slides from where it was to the new choice (0.4 s), and it
 * never regrows from nothing. A toggle that is hidden measures zero, so it is
 * not measured then (the thumb keeps its last place instead of jumping to the
 * left edge). The first placement does not animate.
 */
import { useLayoutEffect, useRef, useState, type RefObject } from 'react';
import { cn } from '@/lib/utils';

interface Place {
  x: number;
  width: number;
}

/**
 * Tracks the active segment inside `root` (`activeSelector`, for example
 * `[data-state=on]`) and returns where the thumb sits. Re-measures when the
 * choice or a size changes.
 */
export function useSegmentThumb(root: RefObject<HTMLElement | null>, activeSelector: string) {
  const [place, setPlace] = useState<Place | null>(null);
  const [animate, setAnimate] = useState(false);
  const placed = useRef(false);

  useLayoutEffect(() => {
    const el = root.current;
    if (!el) return undefined;
    const measure = () => {
      if (el.offsetWidth === 0) return; // hidden: keep the last place
      const active = el.querySelector<HTMLElement>(activeSelector);
      if (!active || active.offsetWidth === 0) {
        setPlace(null);
        return;
      }
      const next = { x: active.offsetLeft, width: active.offsetWidth };
      setPlace((prev) => (prev && prev.x === next.x && prev.width === next.width ? prev : next));
      if (!placed.current) {
        placed.current = true;
        // Let the first placement paint, then animate every later move.
        requestAnimationFrame(() => setAnimate(true));
      }
    };
    measure();
    const mutations = new MutationObserver(measure);
    mutations.observe(el, { subtree: true, attributes: true, attributeFilter: ['data-state', 'aria-checked', 'aria-selected'] });
    const sizes = new ResizeObserver(measure);
    sizes.observe(el);
    return () => {
      mutations.disconnect();
      sizes.disconnect();
    };
  }, [root, activeSelector]);

  return { place, animate };
}

/** The thumb itself; render it as the first child of the segment row. */
export function SegmentThumb({ place, animate, className }: { place: Place | null; animate: boolean; className?: string }) {
  if (!place) return null;
  return (
    <span
      aria-hidden="true"
      data-fx-thumb=""
      data-fx-thumb-animate={animate ? '' : undefined}
      className={cn(
        'pointer-events-none absolute inset-y-0.5 left-0 rounded-(--fx-r-s) bg-(--fx-surface) shadow-[0_1px_3px_var(--fx-lift)]',
        className,
      )}
      style={{ translate: `${place.x}px 0`, width: place.width }}
    />
  );
}
