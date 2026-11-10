/**
 * T2 fix round 2 (`use-horizontal-overflow.ts`): the hook must observe EVERY
 * child of the scroller, not just `firstElementChild` (a `Tabs` strip refs
 * the LIST itself, so its first child is the first TRIGGER, not a stand-in
 * for the whole strip's content width), and must re-measure + re-observe
 * when a child is added/removed/reordered later - a `MutationObserver` on
 * the scroller itself, not a one-shot mount-time scan.
 */
import * as React from 'react';
import { act, render } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { useHorizontalOverflow } from './use-horizontal-overflow';

function Harness({ items, overflowing }: { items: string[]; overflowing: boolean }) {
  const { ref, isOverflowing } = useHorizontalOverflow<HTMLDivElement>();
  return (
    <div ref={ref} data-testid="scroller" data-overflowing={isOverflowing}>
      {items.map((item) => (
        <span key={item} data-testid={`item-${item}`}>
          {item}
        </span>
      ))}
      {/* Lets the test flip the measured overflow state without a real layout
          engine - jsdom never resolves scrollWidth/clientWidth from content. */}
      <span data-overflow-sentinel={overflowing} />
    </div>
  );
}

/** Stubs scrollWidth/clientWidth so `measure()` sees a real transition. */
function stubMeasurement(el: HTMLElement, getScrollWidth: () => number) {
  Object.defineProperty(el, 'clientWidth', { configurable: true, get: () => 100 });
  Object.defineProperty(el, 'scrollWidth', { configurable: true, get: getScrollWidth });
  Object.defineProperty(el, 'scrollLeft', { configurable: true, value: 0, writable: true });
}

describe('useHorizontalOverflow (T2 fix round 2)', () => {
  it('observes every initial child, not just the first', () => {
    const observeSpy = vi.spyOn(globalThis.ResizeObserver.prototype, 'observe');
    const { container } = render(<Harness items={['a', 'b', 'c']} overflowing={false} />);
    const el = container.querySelector('[data-testid="scroller"]') as HTMLDivElement;

    // The scroller itself, plus EVERY child - fix round 1 only watched
    // `firstElementChild`.
    expect(observeSpy).toHaveBeenCalledWith(el);
    for (const child of Array.from(el.children)) {
      expect(observeSpy).toHaveBeenCalledWith(child);
    }
    observeSpy.mockRestore();
  });

  it('re-observes a child added after mount (fix round 1 only ever saw the mount-time firstElementChild)', async () => {
    const observeSpy = vi.spyOn(globalThis.ResizeObserver.prototype, 'observe');
    const { container, rerender } = render(<Harness items={['a', 'b']} overflowing={false} />);
    observeSpy.mockClear();

    rerender(<Harness items={['a', 'b', 'c']} overflowing={false} />);
    // The MutationObserver callback runs as a microtask after the DOM
    // mutation React just applied.
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    const added = container.querySelector('[data-testid="item-c"]') as HTMLElement;
    expect(observeSpy).toHaveBeenCalledWith(added);
    observeSpy.mockRestore();
  });

  it('a mutation triggers a real re-measure (isOverflowing flips once the scroller genuinely overflows)', async () => {
    let scrollWidth = 100;
    const { container, rerender } = render(<Harness items={['a']} overflowing={false} />);
    const el = container.querySelector('[data-testid="scroller"]') as HTMLDivElement;
    stubMeasurement(el, () => scrollWidth);

    // Still fits - no overflow yet.
    expect(el.getAttribute('data-overflowing')).toBe('false');

    // A new child grows the content past the scroller's box - simulates a
    // late-added tab/column.
    scrollWidth = 400;
    rerender(<Harness items={['a', 'b']} overflowing={false} />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      // rAF-guarded measure - flush the animation frame the mutation
      // handler scheduled.
      await new Promise((resolve) => requestAnimationFrame(resolve));
    });

    expect(el.getAttribute('data-overflowing')).toBe('true');
  });
});
