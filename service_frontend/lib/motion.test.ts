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
 * Ported from `sorento_crm` `lib/motion.test.ts` verbatim (plan 23 section
 * 3.3), the M2 `kind`/`surfaceExitTransition` branches included since this
 * repo's `lib/motion.ts` ships them from the start (D1).
 */
import { describe, expect, it } from 'vitest';
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

describe('Shared surface spring collapses under reduced motion (AC-DLA-19)', () => {
  it('uses the critically damped spring when motion is not reduced', () => {
    expect(surfaceTransition(false)).toBe(SURFACE_SPRING);
    expect(surfaceTransition(null)).toBe(SURFACE_SPRING);
    expect(SURFACE_SPRING).toMatchObject({ type: 'spring', bounce: 0, visualDuration: 0.3 });
  });

  it('collapses to a same-frame transition when the user asked for less motion', () => {
    expect(surfaceTransition(true)).toBe(REDUCED_MOTION_TRANSITION);
    expect(REDUCED_MOTION_TRANSITION.type).not.toBe('spring');
    expect(REDUCED_MOTION_TRANSITION.duration).toBeLessThanOrEqual(0.01);
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
    expect(MENU_SPRING).toMatchObject({ type: 'spring', bounce: 0, visualDuration: 0.2 });
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
    expect(SURFACE_SPRING_EXIT).toMatchObject({ type: 'spring', bounce: 0, visualDuration: 0.2 });
  });

  it('collapses to the reduced-motion transition', () => {
    expect(surfaceExitTransition(true)).toBe(REDUCED_MOTION_TRANSITION);
  });
});

describe('useOpenState mirrors a Radix Root open state (AC-DLA-19)', () => {
  it('is exported as a function with the controlled/uncontrolled contract', () => {
    expect(typeof useOpenState).toBe('function');
    expect(useOpenState.length).toBe(3);
  });
});
