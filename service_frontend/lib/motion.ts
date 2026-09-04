'use client';

import * as React from 'react';
import { useReducedMotion, type Transition } from 'motion/react';

/**
 * The one spring every lightbox/menu surface (Dialog, Sheet, Popover,
 * DropdownMenu) opens and closes with (AC-DLA-19). Critically damped -
 * `bounce: 0` - because none of these are driven by a flick or a drag;
 * overshoot only belongs on a momentum-carrying gesture.
 *
 * `visualDuration` is Apple's "response" half of the damping/response pair,
 * tuned to match `--duration-slow` (300ms, css/config.reui.css) so a JS
 * spring and this app's CSS transitions read at the same pace.
 *
 * A spring re-targets from wherever the value currently sits, so re-opening a
 * surface mid-close continues from its live scale/opacity instead of jumping
 * back to 0 - that is what makes it "interruptible" (AC-DLA-20).
 *
 * Ported from `sorento_crm` `lib/motion.ts` verbatim (plan 23 section 3.3).
 */
export const SURFACE_SPRING: Transition = {
  type: 'spring',
  bounce: 0,
  visualDuration: 0.3,
};

/**
 * The menu/popper family (Popover, DropdownMenu and the rest of the menu
 * primitives) opens on a shorter response than a lightbox: a menu is a
 * quick lookup next to the trigger, not a surface that takes over the
 * screen, so `visualDuration` matches `--duration-base` (200ms) instead of
 * `--duration-slow`.
 */
export const MENU_SPRING: Transition = {
  type: 'spring',
  bounce: 0,
  visualDuration: 0.2,
};

/**
 * The exit half of a lightbox close. Every surface in this file opens on
 * its own response (0.3s for a lightbox, 0.2s for a menu) but closes on the
 * same 0.2s - a close only has to get out of the way, not announce itself,
 * so there is no reason to hold the lightbox's slower in-transition on the
 * way out.
 */
export const SURFACE_SPRING_EXIT: Transition = {
  type: 'spring',
  bounce: 0,
  visualDuration: 0.2,
};

/**
 * Under `prefers-reduced-motion: reduce` the spring collapses to a same-frame
 * opacity change - no scale, no travel, no overshoot.
 */
export const REDUCED_MOTION_TRANSITION: Transition = {
  duration: 0.01,
};

/**
 * The transition a surface should ENTER with, given the user's motion
 * preference and what kind of surface it is. `'lightbox'` (Dialog, Sheet,
 * AlertDialog) is the default; `'menu'` (Popover, DropdownMenu and the rest
 * of the menu family) is 0.2s.
 */
export function surfaceTransition(
  prefersReducedMotion: boolean | null,
  kind: 'lightbox' | 'menu' = 'lightbox',
): Transition {
  if (prefersReducedMotion) return REDUCED_MOTION_TRANSITION;
  return kind === 'menu' ? MENU_SPRING : SURFACE_SPRING;
}

/**
 * The transition a surface should EXIT with - always the shorter 0.2s
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
