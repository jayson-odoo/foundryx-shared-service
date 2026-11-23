/**
 * When the top bar changes with the page's scroll (playbook 0.71.0
 * "Navigation and panels"). Pure, so the thresholds are unit-tested.
 *
 * - Wider screens: once the page scrolls about 64px the top bar merges into
 *   the frozen page header; back under 24px it comes back. The gap between
 *   the two keeps it from flickering at one scroll position.
 * - Phones (720px and narrower): the bar condenses once the page's red
 *   button has scrolled under it, and opens back up when it comes out again.
 *   A page without a red button condenses on the same 64px / 24px rule.
 */

export const FX_MERGE_AT = 64;
export const FX_UNMERGE_BELOW = 24;
export const FX_PHONE_MAX = 720;

/** The merged state after a scroll to `y`, given the state before it. */
export function nextMerged(prev: boolean, y: number): boolean {
  if (!prev && y >= FX_MERGE_AT) return true;
  if (prev && y < FX_UNMERGE_BELOW) return false;
  return prev;
}

/**
 * The condensed state on a phone. `actionBottom` is the bottom edge of the
 * page header's actions (null when the page has none), `barBottom` the top
 * bar's bottom edge, both in viewport pixels.
 */
export function nextCondensed(
  prev: boolean,
  input: { y: number; actionBottom: number | null; barBottom: number },
): boolean {
  if (input.actionBottom === null) return nextMerged(prev, input.y);
  return input.actionBottom <= input.barBottom;
}
