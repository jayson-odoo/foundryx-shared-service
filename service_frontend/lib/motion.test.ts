/**
 * AC-DLA-19 - the shared spring collapses under `prefers-reduced-motion:
 * reduce`, and the menu/lightbox split every surface in T3 resolves through.
 *
 * Dialog, AlertDialog, Sheet, Popover, DropdownMenu (+SubContent),
 * ContextMenu (+SubContent), HoverCard and Menubar all resolve their
 * open/close transition through `surfaceTransition` and their
 * initial/animate/exit targets through `surfaceVariants` - pinning the
 * branch here, once, is what proves every surface collapses to the same
 * near-instant fade rather than each primitive inventing its own
 * reduced-motion escape hatch.
 *
 * Ported from `sorento_crm` `lib/motion.test.ts`, the M2 `kind`/
 * `surfaceExitTransition` branches included since this repo's `lib/motion.ts`
 * ships them from the start (D1). T3 fix round 1 (D16) adds the settle-time
 * assertions below, run against the REAL `motion-dom` spring generator
 * rather than the config object alone - `vitest.setup.ts` sets
 * `MotionGlobalConfig.skipAnimations = true` globally so no rendered
 * component ever exercises the generator, which is what let the previous
 * round's `visualDuration: 0.3`/`0.2` literals ship settling at 559ms/390ms
 * (~1.9x their intended 300ms/200ms) with every test still green.
 */
import { spring } from 'motion-dom';
import { act, renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import {
  MENU_SPRING,
  REDUCED_MOTION_TRANSITION,
  SURFACE_SPRING,
  SURFACE_SPRING_EXIT,
  surfaceExitTransition,
  surfaceTransition,
  surfaceVariants,
  useOpenState,
} from './motion';

/**
 * Runs the actual `motion-dom` spring generator millisecond-by-millisecond
 * until it reports `done` (i.e. the point `AnimatePresence` would unmount an
 * exiting child), returning that wall-clock time. `spring().next(t)` takes
 * `t` in MILLISECONDS despite `visualDuration` itself being in seconds.
 */
function measureSettleMs(transition: { bounce?: number; visualDuration?: number }): number {
  const generator = spring({ keyframes: [0, 1], bounce: transition.bounce ?? 0, visualDuration: transition.visualDuration });
  for (let t = 0; t <= 2000; t += 1) {
    const state = generator.next(t);
    if (state.done) return t;
  }
  throw new Error('spring never settled within 2000ms');
}

describe('Shared surface spring collapses under reduced motion (AC-DLA-19)', () => {
  it('uses the critically damped spring when motion is not reduced', () => {
    expect(surfaceTransition(false)).toBe(SURFACE_SPRING);
    expect(surfaceTransition(null)).toBe(SURFACE_SPRING);
    expect(SURFACE_SPRING).toMatchObject({ type: 'spring', bounce: 0, visualDuration: 0.15 });
  });

  it('collapses to a quick fade - gentler, not zero - when the user asked for less motion (D16)', () => {
    expect(surfaceTransition(true)).toBe(REDUCED_MOTION_TRANSITION);
    expect(REDUCED_MOTION_TRANSITION.type).not.toBe('spring');
    // --duration-fast (css/config.reui.css) - a same-frame 0.01s pop reads
    // as a flicker, not a fade (T3 fix round 1 finding 3).
    expect(REDUCED_MOTION_TRANSITION.duration).toBe(0.15);
  });

  it('scales up from the trigger when motion is not reduced', () => {
    const variants = surfaceVariants(false);
    expect(variants.initial).toMatchObject({ opacity: 0, scale: 0.96 });
    expect(variants.animate).toMatchObject({ opacity: 1, scale: 1 });
    expect(variants.exit).toMatchObject({ opacity: 0, scale: 0.96 });
  });

  it('drops the scale under reduced motion and keeps only the fade', () => {
    const variants = surfaceVariants(true);
    expect(variants.initial).toStrictEqual({ opacity: 0 });
    expect(variants.animate).toStrictEqual({ opacity: 1 });
    expect(variants.exit).toStrictEqual({ opacity: 0 });
    expect(variants.initial).not.toHaveProperty('scale');
  });
});

describe('surfaceTransition(kind) picks the menu preset', () => {
  it('defaults to the lightbox spring when no kind is passed', () => {
    expect(surfaceTransition(false)).toBe(SURFACE_SPRING);
  });

  it('returns the lightbox spring for kind "lightbox"', () => {
    expect(surfaceTransition(false, 'lightbox')).toBe(SURFACE_SPRING);
  });

  it('returns the menu spring for kind "menu"', () => {
    expect(surfaceTransition(false, 'menu')).toBe(MENU_SPRING);
    expect(MENU_SPRING).toMatchObject({ type: 'spring', bounce: 0, visualDuration: 0.1 });
  });

  it('collapses both kinds to the same reduced-motion transition', () => {
    expect(surfaceTransition(true, 'lightbox')).toBe(REDUCED_MOTION_TRANSITION);
    expect(surfaceTransition(true, 'menu')).toBe(REDUCED_MOTION_TRANSITION);
  });
});

describe('surfaceExitTransition', () => {
  it('returns the shorter exit spring when motion is not reduced', () => {
    expect(surfaceExitTransition(false)).toBe(SURFACE_SPRING_EXIT);
    expect(surfaceExitTransition(null)).toBe(SURFACE_SPRING_EXIT);
    expect(SURFACE_SPRING_EXIT).toMatchObject({ type: 'spring', bounce: 0, visualDuration: 0.1 });
  });

  it('collapses to the reduced-motion transition', () => {
    expect(surfaceExitTransition(true)).toBe(REDUCED_MOTION_TRANSITION);
  });
});

/**
 * D16 / T3 fix round 1 finding 3 - the constants above are meaningless
 * without proving what they actually settle at. These run the real
 * `motion-dom` generator (imported directly, bypassing the `skipAnimations`
 * global) rather than eyeballing a DevTools trace.
 */
describe('Measured settle time (D16, motion-dom spring generator)', () => {
  it('SURFACE_SPRING (lightbox open) settles between 250ms and 350ms', () => {
    const ms = measureSettleMs(SURFACE_SPRING);
    expect(ms).toBeGreaterThanOrEqual(250);
    expect(ms).toBeLessThanOrEqual(350);
  });

  it('MENU_SPRING settles between 180ms and 240ms', () => {
    const ms = measureSettleMs(MENU_SPRING);
    expect(ms).toBeGreaterThanOrEqual(180);
    expect(ms).toBeLessThanOrEqual(240);
  });

  it('SURFACE_SPRING_EXIT settles between 180ms and 240ms', () => {
    const ms = measureSettleMs(SURFACE_SPRING_EXIT);
    expect(ms).toBeGreaterThanOrEqual(180);
    expect(ms).toBeLessThanOrEqual(240);
  });
});

describe('useOpenState mirrors a Radix Root open state (AC-DLA-19)', () => {
  it('is uncontrolled by default: starts at defaultOpen and updates its own state', () => {
    const onOpenChange = vi.fn();
    const { result } = renderHook(() => useOpenState(undefined, false, onOpenChange));

    expect(result.current[0]).toBe(false);

    act(() => {
      result.current[1](true);
    });

    expect(result.current[0]).toBe(true);
    expect(onOpenChange).toHaveBeenCalledWith(true);
  });

  it('defaultOpen seeds the initial uncontrolled value', () => {
    const { result } = renderHook(() => useOpenState(undefined, true, undefined));
    expect(result.current[0]).toBe(true);
  });

  it('controlled `open` wins over internal state, which stays untouched', () => {
    const onOpenChange = vi.fn();
    const { result, rerender } = renderHook(
      ({ open }: { open: boolean }) => useOpenState(open, false, onOpenChange),
      { initialProps: { open: false } },
    );

    expect(result.current[0]).toBe(false);

    // Calling setOpen while controlled must NOT flip the internal
    // uncontrolled state - only the caller's onOpenChange, which is
    // expected to feed a new `open` prop back in.
    act(() => {
      result.current[1](true);
    });
    expect(onOpenChange).toHaveBeenCalledWith(true);
    expect(result.current[0]).toBe(false); // still controlled by the stale `open` prop

    rerender({ open: true });
    expect(result.current[0]).toBe(true);
  });

  it('fires onOpenChange in both controlled and uncontrolled modes', () => {
    const uncontrolledChange = vi.fn();
    const { result: uncontrolled } = renderHook(() => useOpenState(undefined, false, uncontrolledChange));
    act(() => uncontrolled.current[1](true));
    expect(uncontrolledChange).toHaveBeenCalledWith(true);

    const controlledChange = vi.fn();
    const { result: controlled } = renderHook(() => useOpenState(false, false, controlledChange));
    act(() => controlled.current[1](true));
    expect(controlledChange).toHaveBeenCalledWith(true);
  });

  it('is exported as a function with the controlled/uncontrolled contract', () => {
    expect(typeof useOpenState).toBe('function');
    expect(useOpenState.length).toBe(3);
  });
});
