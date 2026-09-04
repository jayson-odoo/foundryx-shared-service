/**
 * Every Radix menu/select/popover/dialog surface is portalled to `<body>`, so a click,
 * wheel, or focus event landing in one reports a target with no DOM ancestry back to
 * whatever opened it. Code that reads "not a descendant of the thing I own" as "outside"
 * - a dialog's outside-click guard, an inline editor's row-commit guard - needs to treat
 * these surfaces as still-inside instead, or it dismisses/discards the very thing the
 * person is interacting with. One selector, shared, so `dialog.tsx`'s outside-click guard
 * and any future row-commit guard cannot drift into two different lists of the same
 * concept.
 *
 * Ported from `sorento_crm` `components/common/floatingAncestry.ts` (T3 fix round 1
 * finding 8) with this repo's own `data-slot` values added (`sheet-content`,
 * `drawer-content` - vaul's mobile nav) so the guard covers every stacked surface this
 * repo actually ships, not just Sorento's set.
 *
 * `[data-radix-focus-guard]` is Radix's own tab-trap sentinel, appended as a direct child
 * of `<body>` (a sibling of every portal root, not a descendant of any of them) - a focus
 * hop through one is a transient step INSIDE a modal's focus trap, not a departure from it.
 */
const FLOATING_SURFACE_SELECTOR =
  '[data-radix-popper-content-wrapper], [data-radix-menu-content], [data-radix-popover-content], [data-radix-select-content], [data-radix-context-menu-content], [data-slot="dropdown-menu-content"], [data-slot="popover-content"], [data-slot="select-content"], [data-slot="dialog-content"], [data-slot="alert-dialog-content"], [data-slot="sheet-content"], [data-slot="drawer-content"], [role="menu"], [role="menuitem"], [role="listbox"], [role="option"], [role="dialog"], [role="alertdialog"], [cmdk-root], [data-radix-focus-guard]';

export function focusIsInsideFloating(node: Element | null): boolean {
  if (!node) return false;
  return Boolean(node.closest(FLOATING_SURFACE_SELECTOR));
}

/**
 * Is this element physically rendered inside an open Dialog/AlertDialog's own content -
 * i.e. would a popover anchored here need to win Dialog's `react-remove-scroll` lock to
 * scroll on a real wheel gesture?
 */
export function isInsideOpenDialog(node: Element | null): boolean {
  if (!node) return false;
  return Boolean(node.closest('[data-slot="dialog-content"], [data-slot="alert-dialog-content"]'));
}
