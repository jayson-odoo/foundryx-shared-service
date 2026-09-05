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
 * Radix's `onPointerDownOutside`/`onInteractOutside`/`onFocusOutside` all wrap
 * the real DOM event in a `CustomEvent` whose `detail.originalEvent` carries the
 * actual pointer/focus event - `event.target` on the CustomEvent itself is the
 * DialogContent/AlertDialogContent/SheetContent node, not the thing that was
 * actually clicked. `dialog.tsx`/`alert-dialog.tsx`/`sheet.tsx` each mount this
 * with their own `mountedAtRef` (T3 fix round 1 finding 8; factored out here in
 * T3 fix round 2 finding 5 so the guard logic is unit-testable in one place
 * instead of duplicated verbatim in three files).
 *
 * Two independent reasons to swallow the interaction (`event.preventDefault()`,
 * which stops Radix reading it as "close me"):
 * 1. The target is inside ANOTHER floating surface (a menu/select/popover that
 *    just opened this one, or a dialog stacked above this one) -
 *    `focusIsInsideFloating`.
 * 2. The event fires within a short grace window after this content mounted -
 *    the trailing pointer/focus event from whatever surface opened this one,
 *    which can still be unwinding its own unmount on the same tick.
 */
export function createOutsideInteractionGuard(mountedAtRef: { current: number }) {
  return (event: Event) => {
    const detail = (event as CustomEvent<{ originalEvent?: Event }>).detail;
    const original = detail?.originalEvent;
    const target = (original?.target ?? event.target) as Element | null;
    if (focusIsInsideFloating(target)) {
      event.preventDefault();
      return;
    }
    if (mountedAtRef.current && performance.now() - mountedAtRef.current < 300) {
      event.preventDefault();
      return;
    }
  };
}
