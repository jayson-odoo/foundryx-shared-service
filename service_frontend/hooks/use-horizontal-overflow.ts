'use client';

import * as React from 'react';

/**
 * Tracks whether a scroll container has more content to its right.
 *
 * A strip that scrolls sideways with no visible scrollbar is invisible unless
 * something marks the edge, so both surfaces that scroll horizontally - the
 * tab list (AC-DLA-12) and the DataGrid scroller (AC-DLA-13) - fade their
 * right edge while there is more to see. The fade has to vanish once the
 * container fits or once the user has reached the end, or it reads as a
 * permanently half-drawn column.
 *
 * Ported (API-compatible) from `sorento_crm` `hooks/use-horizontal-overflow.ts`
 * (plan 23 section 3.2), with two fix-round-1 hardenings (AC-DLA-14):
 * - the scroll handler is rAF-guarded, so a fast scroll never queues more
 *   than one measure per frame;
 * - the FIRST CHILD (the table / the tab strip itself) is ALSO observed, not
 *   just the scroller - a column resize, a column hide/show, a reorder, or a
 *   late-added tab changes the CHILD's content width while the scroller's
 *   own box stays the same size, so watching only the scroller misses it.
 */
export function useHorizontalOverflow<T extends HTMLElement>() {
  const ref = React.useRef<T | null>(null);
  const [state, setState] = React.useState({ isOverflowing: false, isAtEnd: true });

  const measure = React.useCallback(() => {
    const el = ref.current;
    if (!el) return;
    // 1px of slack: fractional layout widths otherwise leave a fade over a
    // container the user has already scrolled to the end of.
    const isOverflowing = el.scrollWidth - el.clientWidth > 1;
    const isAtEnd = !isOverflowing || Math.abs(el.scrollWidth - el.clientWidth - Math.abs(el.scrollLeft)) <= 1;
    setState((prev) =>
      prev.isOverflowing === isOverflowing && prev.isAtEnd === isAtEnd ? prev : { isOverflowing, isAtEnd },
    );
  }, []);

  React.useEffect(() => {
    measure();
    const el = ref.current;
    if (!el) return;

    // rAF-guard: a scroll event can fire many times per frame, and only the
    // LAST position before paint matters for this measurement.
    let rafId: number | null = null;
    const scheduleMeasure = () => {
      if (rafId !== null) return;
      rafId = requestAnimationFrame(() => {
        rafId = null;
        measure();
      });
    };

    const observer = new ResizeObserver(scheduleMeasure);
    observer.observe(el);
    if (el.firstElementChild) observer.observe(el.firstElementChild);
    el.addEventListener('scroll', scheduleMeasure, { passive: true });
    window.addEventListener('resize', scheduleMeasure);

    return () => {
      if (rafId !== null) cancelAnimationFrame(rafId);
      observer.disconnect();
      el.removeEventListener('scroll', scheduleMeasure);
      window.removeEventListener('resize', scheduleMeasure);
    };
  }, [measure]);

  return {
    ref,
    isOverflowing: state.isOverflowing,
    isAtEnd: state.isAtEnd,
    isFading: state.isOverflowing && !state.isAtEnd,
  };
}
