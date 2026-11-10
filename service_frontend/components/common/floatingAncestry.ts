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
 *
 * `[data-sonner-toaster]` (plan 26 review round 2, blocker 1 follow-up): sonner's
 * toaster is ALSO a top-level `<body>` portal, sibling to every Dialog's own
 * portal root. Once a toast became clickable over an open modal Dialog (the
 * `pointer-events-auto` fix in `sonner.tsx`), clicking its Cancel button
 * reads to Radix as a pointerdown OUTSIDE the dialog's content and closes
 * it - discarding the very countdown the click was meant to interact with
 * (found live: "Manage segments" + a row's deferred-delete countdown toast).
 * Every toast-hosted control must stay "inside" any dialog beneath it, the
 * same way a popover/menu opened FROM a dialog already does.
 */
const FLOATING_SURFACE_SELECTOR =
  '[data-radix-popper-content-wrapper], [data-radix-menu-content], [data-radix-popover-content], [data-radix-select-content], [data-radix-context-menu-content], [data-slot="dropdown-menu-content"], [data-slot="popover-content"], [data-slot="select-content"], [data-slot="dialog-content"], [data-slot="alert-dialog-content"], [data-slot="sheet-content"], [data-slot="drawer-content"], [role="menu"], [role="menuitem"], [role="listbox"], [role="option"], [role="dialog"], [role="alertdialog"], [cmdk-root], [data-radix-focus-guard], [data-sonner-toaster], [data-sonner-toast]';

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
