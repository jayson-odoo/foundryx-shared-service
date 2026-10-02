/**
 * Class strings shared by more than one primitive.
 *
 * Three lightbox surfaces (dialog, alert dialog, sheet) and a set of controls
 * (button, checkbox, switch, radio, toggle, tab trigger, and the
 * keyboard-navigable menu items) have to agree on the scrim, the pressed
 * state and the touch target. Written once here so they cannot drift apart
 * one file at a time.
 *
 * Ported from `sorento_crm` `components/ui/primitive-classes.ts` (see plan 23
 * section 3.2, AC-DLA-09). This repo's `PRESSED_CLASS` already carries the
 * `duration-fast`/`ease-standard` tokens (Sorento's later M1-01 refinement) -
 * `css/config.reui.css`'s `@theme` default transition points at the same two
 * tokens, but naming them explicitly here means a reader of just this file
 * does not have to go looking for the theme to know what curve a press runs
 * on.
 */

/**
 * The one scrim: `--scrim` (50%/62% black, see `css/config.reui.css`) with an
 * 8px blur, faded in and out with the surface via `data-state`.
 *
 * `prefers-reduced-transparency` and `prefers-contrast: more` are handled by
 * the merged preference block in `css/styles.css` (T1) - no arbitrary media
 * query duplicated here.
 */
export const OVERLAY_CLASS =
  'fixed inset-0 z-(--z-modal) bg-(--scrim) backdrop-blur-sm ' +
  'data-[state=open]:animate-in data-[state=closed]:animate-out ' +
  'data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0';

/**
 * The same scrim, minus the CSS fade-in/out.
 *
 * A surface that drives its overlay's opacity with the shared spring from
 * `lib/motion.ts` (T3) instead of `animate-in`/`animate-out` needs this
 * variant: a still-running CSS keyframe animation on `opacity` wins the
 * cascade over a concurrent JS-driven inline style on the same property, so
 * the two would fight rather than agree on a final value. Not wired into any
 * primitive yet in T2 - T3 swaps Dialog/Sheet onto it when they move to the
 * spring (plan 23 section 3.2 risk note).
 */
export const OVERLAY_CLASS_STATIC = 'fixed inset-0 z-(--z-modal) bg-(--scrim) backdrop-blur-sm';

/**
 * Pressed feedback: the control answers on pointer DOWN, not on release.
 *
 * A 3% shrink is enough to read as a physical press at every control size,
 * and it is suppressed for anyone who asked for less motion.
 *
 * `scale` is named in the transition list ALONGSIDE `transform` (fix round
 * 1, AC-DLA-09): Tailwind 4 compiles `active:scale-[0.97]` to the standalone
 * CSS `scale` property, not `transform` - `transition-[transform,...]` alone
 * never animates it and the press snaps instead of easing. Applied to
 * Button (lg/md/icon), checkbox, switch, radio, toggle, tab trigger.
 */
export const PRESSED_CLASS =
  'transition-[transform,scale,color,background-color,border-color,box-shadow] ' +
  'duration-(--duration-fast) ease-(--ease-standard) ' +
  'active:scale-[0.97] motion-reduce:active:scale-100';

/**
 * The shrink alone, no colour transition - for a roving-focus item (Radix
 * `DropdownMenuItem`/`ContextMenuItem`/`MenubarItem`): arrow keys move
 * `focus:bg-accent` between siblings, and a colour EASE on that move reads as
 * motion triggered by the keyboard, not the click - a hard-fail this plan's
 * own design-language rules land in T8. `CommandItem` (keyboard-driven,
 * 100+/day) and the slider thumb (a drag is a hold) carry NEITHER class.
 *
 * Same `scale` fix as `PRESSED_CLASS` (`transition-transform` covers both
 * `transform` and the standalone `scale` Tailwind 4 property, so a single
 * property name is enough here where colour is not in the list at all).
 */
export const PRESSED_TRANSFORM_CLASS =
  'transition-transform duration-(--duration-fast) ease-(--ease-standard) ' +
  'active:scale-[0.97] motion-reduce:active:scale-100';

/**
 * A 44x44 touch target on a coarse pointer, without changing the rendered size.
 *
 * The target is an invisible centred pseudo-element, so a 20px checkbox stays
 * a 20px checkbox and still catches a thumb. `relative` is on the control
 * itself.
 *
 * NOT for a control in a dense cluster. The target overflows its own box, so
 * on the pagination strip - 28px buttons 4px apart - the boxes overlap and a
 * thumb aimed at one page lands on the next. Applied to button sizes `lg`,
 * `md` and `icon`, and to checkbox / switch / radio, which are never packed
 * that tightly; `sm` buttons are left alone.
 */
export const COARSE_HIT_TARGET_CLASS =
  'relative pointer-coarse:after:absolute pointer-coarse:after:left-1/2 pointer-coarse:after:top-1/2 ' +
  'pointer-coarse:after:h-full pointer-coarse:after:w-full ' +
  'pointer-coarse:after:min-h-11 pointer-coarse:after:min-w-11 ' +
  'pointer-coarse:after:-translate-x-1/2 pointer-coarse:after:-translate-y-1/2 ' +
  "pointer-coarse:after:content-['']";
