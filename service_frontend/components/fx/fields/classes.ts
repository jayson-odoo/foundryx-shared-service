/**
 * Class strings shared by the Foundryx UIUX fields (playbook 0.71.0 "Fields").
 * Only fx components use them, and fx components render only while the switch
 * is on, so none of this reaches a page with the switch off.
 */

/**
 * The field box: every field (text, number, date, dropdown, text area,
 * search) lifts 2px under the mouse, its border darkens, the background tints
 * and a soft shadow appears; a disabled field does not react. Keyboard focus
 * draws one clear ring on the box. `pointer-coarse:text-base` (AC-DLA-52)
 * stays on every size so iOS never zooms a focused field.
 */
export const FX_FIELD =
  'border border-(--fx-line-2) bg-(--fx-surface) text-(--fx-ink) placeholder:text-(--fx-ink-3) ' +
  'rounded-(--fx-r-m) shadow-none outline-none ' +
  'transition-[translate,border-color,background-color,box-shadow] duration-(--fx-t-hover) ease-(--fx-ease-out) ' +
  'enabled:hover:-translate-y-0.5 enabled:hover:border-(--fx-ink-3) enabled:hover:bg-(--fx-surface-2) ' +
  'enabled:hover:shadow-[0_4px_12px_var(--fx-shade)] ' +
  'focus-visible:border-(--fx-link) focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-(--fx-link)/20 ' +
  'disabled:cursor-not-allowed disabled:opacity-60 read-only:bg-(--fx-surface-2) ' +
  'aria-invalid:border-(--fx-act) aria-invalid:ring-(--fx-act)/15';

/**
 * The same look for a box that wraps a real input (money field, date field,
 * search box): hover and focus are read from the inner input.
 */
export const FX_FIELD_BOX =
  'flex items-center border border-(--fx-line-2) bg-(--fx-surface) text-(--fx-ink) rounded-(--fx-r-m) ' +
  'transition-[translate,border-color,background-color,box-shadow] duration-(--fx-t-hover) ease-(--fx-ease-out) ' +
  'not-has-disabled:hover:-translate-y-0.5 not-has-disabled:hover:border-(--fx-ink-3) not-has-disabled:hover:bg-(--fx-surface-2) ' +
  'not-has-disabled:hover:shadow-[0_4px_12px_var(--fx-shade)] ' +
  'has-focus-visible:border-(--fx-link) has-focus-visible:ring-[3px] has-focus-visible:ring-(--fx-link)/20 ' +
  'has-disabled:cursor-not-allowed has-disabled:opacity-60 ' +
  'has-aria-invalid:border-(--fx-act) has-aria-invalid:ring-(--fx-act)/15';

/** The bare input inside an `FX_FIELD_BOX`: no border, ring or background of its own. */
export const FX_FIELD_INNER =
  'min-w-0 flex-1 bg-transparent text-(--fx-ink) placeholder:text-(--fx-ink-3) outline-none focus-visible:outline-none disabled:cursor-not-allowed';

/** Field heights by density, matching the existing Input sizes. */
export const FX_FIELD_SIZE = {
  sm: 'h-7 px-2.5 text-xs pointer-coarse:text-base',
  md: 'h-8.5 px-3 text-[0.8125rem] leading-(--text-sm--line-height) pointer-coarse:text-base',
  lg: 'h-10 px-4 text-sm pointer-coarse:text-base',
} as const;

export type FxFieldSize = keyof typeof FX_FIELD_SIZE;

/**
 * A menu surface (dropdown lists, the calendar): surface colour, 12px
 * corners, a soft shadow, above the page.
 */
export const FX_MENU =
  'rounded-[12px] border border-(--fx-line) bg-(--fx-surface) text-(--fx-ink) shadow-[0_12px_32px_var(--fx-lift)]';

/**
 * One row of a menu: tinted under the pointer or the keyboard.
 *
 * Disabled is matched on the attribute VALUE, never on the bare attribute:
 * cmdk writes `data-disabled="false"` on every enabled row (and "true" when
 * disabled), which a bare `data-disabled:` variant would treat as disabled.
 * Radix rows write `data-disabled=""` only while disabled, hence the second form.
 */
export const FX_MENU_ROW =
  'flex w-full cursor-default select-none items-center gap-2 rounded-(--fx-r-s) px-2 py-1.5 text-sm text-(--fx-ink) outline-none ' +
  'data-[selected=true]:bg-(--fx-link-bg) data-[highlighted]:bg-(--fx-link-bg) focus:bg-(--fx-link-bg) ' +
  "data-[disabled=true]:pointer-events-none data-[disabled=true]:opacity-50 data-[disabled='']:pointer-events-none data-[disabled='']:opacity-50";
