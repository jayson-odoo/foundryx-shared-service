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
 * (plan 23 section 3.2), with fix-round hardenings (AC-DLA-14):
 * - the scroll handler is rAF-guarded, so a fast scroll never queues more
 *   than one measure per frame;
 * - fix round 1: the scroller's CHILDREN are ALSO observed, not just the
 *   scroller box itself - a column resize, a column hide/show, or a reorder
 *   changes a child's content width while the scroller's own box stays the
 *   same size, so watching only the scroller misses it;
 * - fix round 2: for `Tabs`, the ref sits on the LIST itself (`TabsList` -
 *   see `tabs.tsx`), so that element's own first child is the first TRIGGER,
 *   not "the strip" - observing only `firstElementChild` silently missed
 *   every trigger after the first. Now EVERY child is observed, AND a
 *   `MutationObserver` on `el` (childList) re-measures AND re-observes on
 *   any add/remove - so a tab added/removed/relabelled, or a column
 *   reordered, keeps the fade accurate without a remount.
 */
export function useHorizontalOverflow<T extends HTMLElement>() {
  const ref = React.useRef<T | null>(null);
  const [state, setState] = React.useState({
    isOverflowing: false,
    isAtEnd: true,
  });

  const measure = React.useCallback(() => {
    const el = ref.current;
    if (!el) return;
    // 1px of slack: fractional layout widths otherwise leave a fade over a
    // container the user has already scrolled to the end of.
    const isOverflowing = el.scrollWidth - el.clientWidth > 1;
    const isAtEnd =
      !isOverflowing ||
      Math.abs(el.scrollWidth - el.clientWidth - Math.abs(el.scrollLeft)) <= 1;
    setState((prev) =>
      prev.isOverflowing === isOverflowing && prev.isAtEnd === isAtEnd
        ? prev
        : { isOverflowing, isAtEnd },
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
    // Every child (fix round 2), not just the first - `TabsList` refs the
    // strip itself, so its first child is the first TRIGGER, not a single
    // wrapper standing in for the whole strip's content width.
    for (const child of Array.from(el.children)) observer.observe(child);

    // Re-measure AND re-observe on any add/remove (fix round 2) - a new tab,
    // a removed column, or a reorder changes WHICH elements need watching,
    // not just their size.
    const mutationObserver = new MutationObserver(() => {
      for (const child of Array.from(el.children)) observer.observe(child);
      scheduleMeasure();
    });
    mutationObserver.observe(el, { childList: true });

    el.addEventListener('scroll', scheduleMeasure, { passive: true });
    window.addEventListener('resize', scheduleMeasure);

    return () => {
      if (rafId !== null) cancelAnimationFrame(rafId);
      observer.disconnect();
      mutationObserver.disconnect();
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
