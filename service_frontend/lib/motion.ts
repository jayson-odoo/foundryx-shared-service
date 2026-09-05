'use client';

import * as React from 'react';
import { useReducedMotion, type Transition } from 'motion/react';

/**
 * The one spring every lightbox/menu surface (Dialog, Sheet, Popover,
 * DropdownMenu) opens and closes with (AC-DLA-19). Critically damped -
 * `bounce: 0` - because none of these are driven by a flick or a drag;
 * overshoot only belongs on a momentum-carrying gesture.
 *
 * `visualDuration` is Apple's "response" half of the damping/response pair -
 * it is NOT the wall-clock length of the animation. A `bounce: 0` spring
 * actually settles (motion-dom's generator reports `done`) at roughly 1.9x
 * `visualDuration`: measured with `spring({ keyframes: [0,1], bounce: 0,
 * visualDuration })` from `motion-dom`, 0.3 settles at 559ms and 0.2 at
 * 390ms - both well past this app's own `--duration-slow` (300ms) and
 * `--duration-base` (200ms) tokens they were meant to match (T3 fix round 1,
 * D16). `0.15` is the value that actually lands a lightbox around 300ms
 * (measured 302ms) the way the original comment intended.
 *
 * A spring re-targets from wherever the value currently sits, so re-opening a
 * surface mid-close continues from its live scale/opacity instead of jumping
 * back to 0 - that is what makes it "interruptible" (AC-DLA-20).
 *
 * Ported from `sorento_crm` `lib/motion.ts` (plan 23 section 3.3); the
 * `visualDuration` values below diverge from Sorento's literal 0.3/0.2/0.2
 * per D16 - fed back upstream as BL-SS-049.
 */
export const SURFACE_SPRING: Transition = {
  type: 'spring',
  bounce: 0,
  visualDuration: 0.15,
};

/**
 * The menu/popper family (Popover, DropdownMenu and the rest of the menu
 * primitives) opens on a shorter response than a lightbox: a menu is a
 * quick lookup next to the trigger, not a surface that takes over the
 * screen. `0.1` settles at 210ms (measured), matching the ~200ms a menu
 * previously opened at (D16) - `0.2` would settle at 390ms, nearly double.
 */
export const MENU_SPRING: Transition = {
  type: 'spring',
  bounce: 0,
  visualDuration: 0.1,
};

/**
 * The exit half of a lightbox close. Every surface in this file opens on
 * its own response (0.15s for a lightbox, 0.1s for a menu) but closes on the
 * same 0.1s (settles ~210ms, D16) - a close only has to get out of the way,
 * not announce itself, so there is no reason to hold the lightbox's slower
 * in-transition on the way out. This is also the window Radix's modal
 * `DialogContentModal` keeps `disableOutsidePointerEvents` (and therefore
 * `document.body { pointer-events: none }`) active, so a short, ACCURATE
 * exit duration is what keeps the UI from eating the next click.
 */
export const SURFACE_SPRING_EXIT: Transition = {
  type: 'spring',
  bounce: 0,
  visualDuration: 0.1,
};

/**
 * Under `prefers-reduced-motion: reduce` the spring collapses to a quick
 * opacity-only fade - no scale, no travel, no overshoot. STANDARDS: reduced
 * motion means fewer and GENTLER animations, not zero - `surfaceVariants`
 * already drops the scale, so this only has to remove the spring's travel
 * time, not the fade itself. `0.15` matches `--duration-fast`
 * (css/config.reui.css); `0.01` (fix round 1) was indistinguishable from a
 * hard pop, which is the jarring change reduced motion exists to prevent.
 */
export const REDUCED_MOTION_TRANSITION: Transition = {
  duration: 0.15,
};

/**
 * The transition a surface should ENTER with, given the user's motion
 * preference and what kind of surface it is. `'lightbox'` (Dialog, Sheet,
 * AlertDialog) is the default and settles ~300ms; `'menu'` (Popover,
 * DropdownMenu and the rest of the menu family) settles ~210ms.
 */
export function surfaceTransition(
  prefersReducedMotion: boolean | null,
  kind: 'lightbox' | 'menu' = 'lightbox',
): Transition {
  if (prefersReducedMotion) return REDUCED_MOTION_TRANSITION;
  return kind === 'menu' ? MENU_SPRING : SURFACE_SPRING;
}

/**
 * The transition a surface should EXIT with - always the shorter ~210ms
 * response regardless of what it entered on, so a lightbox opens slower
 * than it closes and a menu's open and close read the same.
 */
export function surfaceExitTransition(prefersReducedMotion: boolean | null): Transition {
  return prefersReducedMotion ? REDUCED_MOTION_TRANSITION : SURFACE_SPRING_EXIT;
}

/**
 * initial/animate/exit for a surface materialising in place: a fade plus a
 * small scale-up. The caller anchors WHERE it grows from via
 * `origin-(--radix-popper-content-transform-origin)` (Radix sets that
 * variable to the trigger side) or a fixed `origin-*` utility for a surface
 * with no Radix popper.
 *
 * Reduced motion drops the scale (an overshoot-free zoom still reads as
 * "motion" to someone who asked for none) and keeps only the fade.
 */
export function surfaceVariants(prefersReducedMotion: boolean | null) {
  if (prefersReducedMotion) {
    return { initial: { opacity: 0 }, animate: { opacity: 1 }, exit: { opacity: 0 } };
  }
  return {
    initial: { opacity: 0, scale: 0.96 },
    animate: { opacity: 1, scale: 1 },
    exit: { opacity: 0, scale: 0.96 },
  };
}

/**
 * Mirrors a Radix Root's open state into plain React state so a `Content`
 * sibling can read it and gate an `<AnimatePresence>` - Radix's own Presence
 * unmounts on `data-state` + a CSS animation it can detect, which a JS spring
 * is not, so the two open/close paths would otherwise race (see dialog.tsx).
 *
 * Same controlled/uncontrolled contract Radix's own primitives use: pass
 * `open` to run it controlled, omit it to let this own the value.
 */
export function useOpenState(
  propOpen: boolean | undefined,
  defaultOpen: boolean,
  onOpenChange: ((open: boolean) => void) | undefined,
): [boolean, (open: boolean) => void] {
  const [uncontrolledOpen, setUncontrolledOpen] = React.useState(defaultOpen);
  const isControlled = propOpen !== undefined;
  const open = isControlled ? propOpen : uncontrolledOpen;

  const setOpen = React.useCallback(
    (next: boolean) => {
      if (!isControlled) setUncontrolledOpen(next);
      onOpenChange?.(next);
    },
    [isControlled, onOpenChange],
  );

  return [open, setOpen];
}

export { useReducedMotion };
export type { Transition };
