# Design language reference

The one-page reference to read before touching any UI file. Written by plan 23 (design-language
alignment, Sorento-parity), which promoted `sorento_crm`'s `documentation/reference/
DESIGN-LANGUAGE.md` into this repo with this repo's paths and roster. Terse reference prose and
tables, not an essay.

## 1. Precedence

Order on conflict, strongest first:

1. `PRINCIPLES.md`
2. This file
3. `docs/reference/frontend-design-language.md` (Resource-shell contract, canvas-editor
   interaction principles - this file owns tokens/motion/primitives, that file owns shell/canvas)
   (arrives with the docs refactor; until it lands, the Resource-shell + canvas-editor rules
   live in AGENTS.md's frontend section)
4. Any installed external design skill (`.claude/skills/emil-design-eng`, `apple-design`,
   `animate`, `review-animations`, `find-animation-opportunities`, `prototype`,
   `pick-ui-library`, `animation-vocabulary`)

An external skill may propose a change to this file via a plan/ADR; it never overrides it inside
a PR.

## 2. Tokens (`service_frontend/css/config.reui.css` unless noted)

| Group | Token | Value |
| --- | --- | --- |
| Motion | `--ease-standard` | `cubic-bezier(0.2, 0, 0, 1)` |
| Motion | `--duration-fast` | `150ms` |
| Motion | `--duration-base` | `200ms` |
| Motion | `--duration-slow` | `300ms` |
| Materials | `--material-regular` | `color-mix(in oklab, var(--background) 72%, transparent)` (header) |
| Materials | `--material-thick` | `color-mix(in oklab, var(--background) 88%, transparent)` (sidebar) |
| Materials | `--material-blur` | `24px` |
| Materials | `--material-edge` | `color-mix(in oklab, var(--foreground) 8%, transparent)` |
| Materials | `--scrim` | `color-mix(in oklab, black 50%, transparent)` (lightbox backdrop; the reduced-transparency preference block in `css/styles.css` raises it and drops the blur) |
| Z-scale | `--z-header` | `10` |
| Z-scale | `--z-sidebar` | `20` |
| Z-scale | `--z-modal` | `50` |
| Z-scale | `--z-banner` | `60` (the impersonation banner sits ABOVE the modal layer on purpose - a banner warning an admin they are impersonating must never hide behind a dialog) |
| Radius | `--radius` | `0.5rem` (base); `--radius-sm/-md/-lg/-xl` derive from it |
| Type | `--font-sans` / `--font-heading` | Inter / Poppins, `css/foundryx-tokens.css` (brand file wins - Foundryx keeps its own type pairing, unlike Sorento's Inter-only) |
| Type | `--text-2xs` / `--text-2sm` | `0.6875rem` / `0.8125rem`, each with a baked line-height |
| Type | tracking | `lg`/`xl`/`2xl` tighten (`-0.01em` to `-0.02em`); `xs`/`2xs` open up (`0.01em`/`0.02em`) - large text tightens, small text opens, so a heading never needs a hand-tuned `tracking-tight` beside it |
| Semantic ink | `--foundryx-success/info/warning` (+ `warning-active`/`warning-accent`) | `css/foundryx-tokens.css` - re-tuned for a real 4.5:1 WCAG AA contrast against both white and `--background` (AC-DLA-07, T1 fix round 3); dark-theme values were already compliant and are unchanged |

Rule (this file's own comment style, `eslint.config.mjs`): no raw `cubic-bezier(...)`, no
`duration-[N]`, no `z-[N]`, no `text-[Npx]` in feature code (`local/no-px-text-class`, AC-DLA-63,
demo1 layout exempt). A new step is added only when a real consumer arrives.

## 3. Motion (`service_frontend/lib/motion.ts`)

- `SURFACE_SPRING`: `{ type: 'spring', bounce: 0, visualDuration: 0.15 }`. The lightbox family's
  entry (Dialog, Sheet, AlertDialog). Critically damped (`bounce: 0`) - none of these are driven
  by a flick or drag, so overshoot has no gesture to answer.
- `MENU_SPRING`: `{ type: 'spring', bounce: 0, visualDuration: 0.1 }`. The menu family's entry
  (Popover, DropdownMenu, ContextMenu, HoverCard, Menubar) - a menu is a quick lookup next to its
  trigger, not a surface that takes over the screen.
- `SURFACE_SPRING_EXIT`: `{ type: 'spring', bounce: 0, visualDuration: 0.1 }`. What EVERY surface
  exits on, lightbox or menu alike - a close only has to get out of the way, not announce itself.
- `REDUCED_MOTION_TRANSITION`: `{ duration: 0.15 }` - an opacity-only fade, no scale, no travel,
  no overshoot. Reduced motion means fewer and GENTLER animations, not zero.
- `surfaceTransition(reduced, kind?: 'lightbox' | 'menu')`, `surfaceExitTransition(reduced)`,
  `surfaceVariants(reduced)` (fade + scale 0.96 -> 1, never scale 0; reduced drops the scale),
  `useOpenState()`, re-exported `useReducedMotion`.
- A spring re-targets from wherever the value currently sits, so re-opening a surface mid-close
  continues live instead of jumping back to 0 (interruptible, AC-DLA-20).
- Origin anchoring: `origin-(--radix-popper-content-transform-origin)` or a fixed `origin-*` for
  a surface with no Radix popper. Modals stay centered.
- `Select` and `Menubar` (Radix exposes no `forceMount` on either) spring IN only and unmount on
  Radix's own schedule - a symmetric CSS opacity fade on `--duration-fast` covers the exit,
  documented inline at each site (AC-DLA-20).
- **Keyboard-triggered surfaces never animate.** `CommandDialog` takes `motion={false}`; the
  global search opener (Cmd/Ctrl+Shift+K) passes it. Any other keyboard-shortcut-opened surface
  does the same.
- **One `TooltipProvider`, app-wide** (`delayDuration={700} skipDelayDuration={300}`); a tooltip
  is instant in and out (no transition, no keyframe).

### D16 - measured settle constants (not Sorento's literal `visualDuration`)

`visualDuration` is motion's perceived-response knob, not the wall-clock length of the
animation. A `bounce: 0` spring actually settles (motion-dom's generator reports `done`) at
roughly 1.9x `visualDuration` - measured with `spring({ keyframes: [0, 1], bounce: 0,
visualDuration })` from `motion-dom`: `0.3` settles at 559ms, `0.2` at 390ms, `0.15` at 302ms,
`0.1` at 210ms. Sorento's literal `0.3`/`0.2`/`0.2` therefore settle well past its own
`--duration-slow`/`--duration-base` tokens they were meant to match. This repo tunes the
`visualDuration` INPUT so the settle time hits the intended target instead: `SURFACE_SPRING`
`0.15` (settles ~300ms, matching `--duration-slow`), `MENU_SPRING`/`SURFACE_SPRING_EXIT` `0.1`
(settles ~210ms, matching `--duration-base`). Intent is identical to Sorento (lightboxes
~300ms in / ~200ms out, menus ~200ms); only the numeric input differs. `lib/motion.test.ts`
pins the settle times by running the generator. Fed back to Sorento as BL-SS-049.

### Rulings

| Topic | Ruling |
| --- | --- |
| Easing curve | `--ease-standard` stays. It is already a custom curve; do not introduce a second one. |
| Duration per surface | Lightboxes (Dialog, Sheet, AlertDialog) = `--duration-slow` in / `--duration-base` out (`SURFACE_SPRING` / `SURFACE_SPRING_EXIT`, D16 settle times above). Menus and popovers = `--duration-base` in and out (`MENU_SPRING` / `SURFACE_SPRING_EXIT`). Tooltip = instant in and out. Pressed feedback = `--duration-fast` (150ms). |
| Frequency gate | Adopt the emil-design-eng frequency table verbatim: 100+ times/day (keyboard shortcuts, command palette toggle) = no animation; tens/day (hover, list navigation, row expand/collapse, tab switch) = none or `--duration-fast` opacity only; occasional (lightboxes, toasts, drawers) = standard surface spring; rare (onboarding, celebration) = may add delight. Keyboard-initiated actions never animate. |
| Layout-property animation during a live drag | A `dnd-kit` drop target reveals via opacity/colour only, never `height`/`margin`/`border-width` - those are LAYOUT properties and force a reflow on every frame of a concurrent drag, fighting the drag's own transform (T8, AC-DLA-67 item 1 - `email-editor/canvas.tsx`'s `DropGap`). |
| Hold vs press | `PRESSED_CLASS` (`active:scale-[0.97]`) never sits on a `cursor-grab` drag handle - a drag is a HOLD (dnd-kit's own transform runs for the whole gesture), so a press-scale would sit compressed for the entire hold and compound with the drag transform. Applies to a pure reorder handle (grip icon, `aria-label="Drag ..."`, no independent click action); a click-to-add-AND-drag palette item (e.g. `email-editor/palette.tsx`) is a real press target too and keeps `PRESSED_CLASS` (T8, AC-DLA-67 item 3; `components/ui/pressed-class.inventory.test.ts` exempts by class content, not a per-file allowlist). Same family as the pre-existing slider-thumb/`CommandItem` carve-out in `components/ui/primitive-classes.ts`. |

### Hard-fails in review

- `transition-all` or `transition: all`
- `transform: scale(0)` as an entrance
- `ease-in` on any entrance
- a raw `cubic-bezier` outside `config.reui.css`
- motion on a keyboard-initiated action
- a new destructive confirm dialog outside the named typed-confirm carve-outs (section 5)
- a raw `<table>` outside the two content allowlist entries (section 4)
- an unlabelled icon button (no `aria-label`/`sr-only` text)
- a bare `Loading...`/`Loading…` string (use a `Skeleton`/spinner icon)
- a direct `sonner` import outside `lib/toast.ts`'s three sanctioned wrapper/mount files
- a `text-[Npx]` class outside the demo1 layout
- `PRESSED_CLASS` (or any `active:scale-*`) on a `cursor-grab` hold element
- a new animation with no `prefers-reduced-motion` handling (use `useReducedMotion` from
  `lib/motion.ts`)

## 4. Primitives roster

| Component | File | When to use |
| --- | --- | --- |
| `ResourceList` | `components/platform/resource-list/resource-list.tsx` | Every product list - server sort/filter/search/paginate, column prefs, segments, bulk actions. Never a hand-rolled table. |
| `ResourceForm` | `components/platform/resource-form/resource-form.tsx` | Every record detail - read + global Edit toggle, `PageHeader` toolbar row, `RecordActions` (pager, gear, primary), dirty-guard `AlertDialog`. |
| `PageHeader` | `components/platform/page-header/page-header.tsx` | The ONE page-title header for lists AND forms; crumbs derive from `useMenu().getBreadcrumb(MENU_SIDEBAR)` unless overridden. No hand-rolled `<h1>`, no `ToolbarPageTitle`. |
| `ActionMenu` (gear) | `components/platform/resource-actions/action-menu.tsx` | Record/row "..." menu; `surface="form"` renders the gear trigger variant, orders secondary actions first, a separator, then destructive (red) last. |
| `DeferredActionButton` / `useDeferredAction` | `components/platform/resource-actions/deferred-action-button.tsx`, `hooks/use-deferred-action.ts` (toast: `components/platform/resource-actions/deferred-toast.tsx`) | Destructive/reversible actions - see section 5 D2/D13. A NEW confirm dialog outside the named carve-outs is a defect. |
| `DataGrid` / `DataGridTable` | `components/ui/data-grid.tsx`, `components/ui/data-grid-table.tsx` | EVERY tabular list; sticky header, pinned columns keep their pinned styles on a phone (nothing pins automatically), `isPlaceholderData` dims rows during a background refetch instead of unmounting them. |
| `StatusBadge` | `components/platform/status-badge/status-badge.tsx` | Status = rounded tinted pill with a dot, resolved via the entity's status registry - never a hand-rolled coloured span. |
| `Tabs` (`variant="line"`) | `components/ui/tabs.tsx` | The default everywhere, dialogs included; pills (`variant="default"`) are reserved for a view TOGGLE that is not navigation (Grid/List, never a set of tabbed panels). |
| `Dialog` / `Sheet` / `AlertDialog` | `components/ui/dialog.tsx`, `sheet.tsx`, `alert-dialog.tsx` | Lightbox surfaces, shared `OVERLAY_CLASS` / `OVERLAY_CLASS_STATIC` from `components/ui/primitive-classes.ts`. |
| `SearchSelect` / `MultiSelect` | `components/platform/search-select/search-select.tsx`, `components/platform/multi-select/multi-select.tsx` | Every dropdown-select; no bare `@/components/ui/select` (`no-restricted-imports`, AC-DLA-63; pre-existing debt tracked as BL-062/BL-SS-043). |
| `ListSearchInput` | `components/platform/list-search-input.tsx` | Every list search box - 200ms debounce, a settling spinner gated behind 250ms of continuous `settling \|\| busy` (never flashes on a fast keystroke pause, T6 fix round 1 item 7). |
| `ClampedText` | `components/platform/clamped-text.tsx` | Truncated text - tooltip on real overflow. Never a bare `truncate`/`line-clamp-*`. |
| `OverflowPills` | `components/platform/overflow-pills/overflow-pills.tsx` | A multi-value cell/field - width-aware `+N` overflow, never an unbounded pill row. |
| `lib/toast` | `lib/toast.ts` for EVERY call site (success/info/warning 4000ms, error `Infinity` + close button; import `toast` from here, never `'sonner'` directly) | Success/error feedback, deferred-action toasts. `components/ui/sonner.tsx` mounts the one `<Toaster position="top-center" closeButton>`. |
| `PageSkeleton` / `ListPageSkeleton` / `RecordPageSkeleton` | `components/platform/skeletons/{page-skeleton,list-page-skeleton,record-page-skeleton}.tsx` | Route-group `loading.tsx` files. `PageSkeleton` (title block + one section card, no rows/pagination) is the GROUP ROOT's neutral fallback for the ~61 segments with no skeleton of their own; `ListPageSkeleton`/`RecordPageSkeleton` are strictly per-segment, matched to what that segment actually renders (AC-DLA-48, T6 fix round 1 item 1 - a group-root list skeleton flashing on a record page is a defect). |
| `lib/menu-path-match` | `lib/menu-path-match.ts` (`matchesMenuPath`/`collectMenuPaths`/`isUnderPath`) | Every "is this the current nav item" check (sidebar, both mega menus) - segment-boundary + most-specific-wins matching, never a naive `path.startsWith(href)` (a naive prefix match lights `/scm` and `/scm-archive` together, AC-DLA-72). |

Pressed + touch: `PRESSED_CLASS` and `COARSE_HIT_TARGET_CLASS` from
`components/ui/primitive-classes.ts` on every pressable EXCEPT a `cursor-grab` hold element or a
keyboard-driven roving-focus item (`CommandItem`, `DropdownMenuItem`/`ContextMenuItem`/
`MenubarItem` - use `PRESSED_TRANSFORM_CLASS`, no colour ease, so arrow-key focus movement never
reads as click-triggered motion). Checked PER ELEMENT, not per file
(`components/ui/pressed-class.inventory.test.ts`) - importing `Button` elsewhere in a file proves
nothing about a separate hand-rolled `<button>` in the same file.

The two content-not-list exceptions to "every table is a `DataGrid`" (D8, AC-DLA-56): a form's
table FIELD (`components/platform/form-renderer/table-field.tsx`) and a rendered email block
(`components/platform/email-editor/block-view.tsx`) render a real `<table>` because they ARE the
content, not a product list. `components/ui/ui-table.inventory.test.ts` pins exactly these two.

## 5. Surviving decisions (plan 23) + T5-T8 rulings

| # | Decision |
| --- | --- |
| D1 | Baseline = the full Sorento standard (Apple Alignment S1-S9 + Motion Round 2 M1-M7). Shared-service may end up ahead of Sorento main. |
| D2 | Delete model = Sorento's grace window (no confirm dialog, server-deferred pending action, 10s destructive / 5s reversible, both tenant-configurable) - BUT the committed action stays what the entity does today (soft-trash where a Trashed view exists, hard delete elsewhere). Sorento's "delete is always hard delete" is NOT adopted. |
| D3 | Data layer stays `useResourceList` (no TanStack Query migration). Rows stay mounted and dim while the next page loads; prefetch on row hover; no skeleton after first load. |
| D4 | Typography: Poppins headings / Inter body stay (Foundryx brand). Sorento's per-step tracking/leading type scale, `font-optical-sizing`, and tight leading on card/dialog titles are adopted. |
| D5 | Detail header = toolbar row (crumbs + title left, ONE Back right) + record card (identity left; pager, gear, one primary right). Wraps under the identity at 375px. |
| D6 | One `PageHeader` for lists AND forms; crumbs derive from `config/menu.config.tsx` via `useMenu().getBreadcrumb`; `ToolbarPageTitle` and hand-rolled `<h1>` retired. |
| D7 | Record-nav stays server-driven and circular over `ctx`/`i` (`hooks/use-record-nav.ts`), gains prefetch of prev/next and carries `from=<rowId>` for row restore on Back. |
| D8 | Every product table is a `DataGrid` - the `@/components/ui/table` importers and raw `<table>` files migrate or are deleted. Allowlist = the two content entries in section 4, nothing else. |
| D9 | One plan, eight slices T1-T8, one branch/evidence dir each, one coder at a time, review between slices. |
| D10 | Motion primitives ported from Sorento verbatim in API (section 3); the 16 dead decor components and `framer-motion` deleted; `motion` is THE animation dependency; `vaul` is the mobile nav drawer. |
| D11 | Tokens live in `css/foundryx-tokens.css` (brand-coloured) or `css/config.reui.css` (motion/material/z-scale/type-scale, matching Sorento's file exactly so the two diff cleanly); preference blocks in `css/styles.css`. |
| D12 | Toasts: `lib/toast.ts` wraps sonner; the 97+ direct `sonner` importers switch to the wrapper; `eslint.config.mjs`'s `no-restricted-imports` bans a new direct import (AC-DLA-63). |
| D13 | Bulk destructive = ONE deferred action naming the count, every selected row dims. Typed-confirmation stays ONLY for the named carve-outs below - see the T5 rulings. |
| D14 | The standard is written into this repo as this file (precedence in section 1), hard-fails added to `PRINCIPLES.md`, PR-checklist rows added to the `reviewer` agent brief, and `/feature` gains the design-skill slots table (section 8). |
| D15 | Browser verification = the `agent-browser` CLI only (user ruling 2026-09-04); the prior browser-automation tooling was fully purged from the repo (T0), with a guard test keeping it that way. |
| D16 | Spring constants set by MEASURED settle time, not Sorento's literal `visualDuration` - see section 3. |

### T5 rulings - the deferred-actions carve-outs (D2/D13)

**Typed-confirmation carve-outs (`confirm.input`, four sites across three files) - the ONLY
places a destructive confirm dialog with a typed field is allowed:**

1. Module uninstall (`confirmName` must equal the module name).
2. Tenant purge, single row (typed slug).
3. Tenant purge, bulk (typed `DELETE`).
4. Documents > Shares, bulk revoke (typed `REVOKE` - restores a shipped sprint-3/05 UAT
   criterion; the ROW-surface revoke stays a plain `deferred` grace window).

**Disclosed plain-confirm exceptions (no typed input, but not on the deferred/grace-window
model either) - named in `confirm-carve-outs.inventory.test.ts`'s `DISCLOSED_PLAIN_CONFIRMS`,
the single source of truth (do not re-list them elsewhere, where they can drift):**

1. Users' Impersonate - D2's "commit after Ns unless Cancelled" model has no meaning for
   starting a session (nothing to undo server-side).
2. The tenant custom-status-edge fallback (`use-tenant-actions.tsx`, BL-SS-052).
3. The operator-console module Deactivate (cross-tenant - acts on ANOTHER tenant's module
   state, outside the deferred-actions engine's own-tenant scope). The STOREFRONT (own-tenant)
   Deactivate IS on the deferred model.

Every other `confirm:` site in the app is `deferred:` (`PENDING_MIGRATION` in the inventory test
is asserted empty).

**A `committing` outcome must never read as settled.** A row claimed by the beat sweep (or a
racing poll from a second tab) but not yet resolved is neither `pending` nor a terminal
outcome - `current()`'s `lastOutcome` stays `null` while a row is `committing`, and the frontend
poll keeps polling rather than toasting success/navigating away on an in-flight commit.

**Every `DeferredActionDef` carries a `module: str` tag** (default `'core'`), gating
`park`/`current`/`cancel`/`commit_one` through the same `active_modules(db, tenant_id)` check
every other catalog (terminology, importers, capabilities) uses - a module DEACTIVATED (not
merely never-installed; grants survive deactivate) must not let a stale role grant still
park/observe/commit that module's actions.

### T6/T7 rulings - shells, sweep, white-label

- **Loading shells**: the route-group root's `loading.tsx` renders the neutral `PageSkeleton`
  (title block + one section card); `ListPageSkeleton`/`RecordPageSkeleton` are generated ONLY
  for segments that actually render a list/record surface (`loading-inventory.test.tsx` is the
  enumeration). A group-root list skeleton flashing before an unrelated real layout is a defect.
- **List search settling**: the spinner glyph shows only once `settling || busy` has been
  continuously true for >= 250ms (`SETTLING_SHOW_DELAY_MS`), clearing on the same tick it goes
  false - a raw `settling` flag flashes Search->Loader->Search on every keystroke pause. `cmdk`
  (`SearchSelect`/`MultiSelect`) filters an in-memory list synchronously and carries NO settling
  glyph at all - there is no fetch for it to represent.
- **Sidebar current-ness = `lib/menu-path-match.ts`, not a naive prefix match** (segment
  boundary + most-specific-wins), applied to the sidebar AND both mega menus. `PRESSED_CLASS` on
  every pressable sidebar item; pressed feedback answers on pointer DOWN, not release.
- **`PRESSED_CLASS` is checked per element, not per file** - a file importing `Button` for one
  control proves nothing about a separate hand-rolled `<button>` elsewhere in the same file
  (`components/ui/pressed-class.inventory.test.ts`).
- **White-label guard**: `lib/white-label.guard.test.ts` bans "Keenthemes"/"keenthemes"/
  "Purchase" outright (no allowlist) and "Metronic" via a disclosed, reported allowlist (build-
  note code comments + one already-tracked live-content exception, BL-SS-057). A branded tenant
  without a logo renders its NAME, never a vendor wordmark.

## 6. Copy and content

- No feature-explanation/how-to copy inside the UI (`PRINCIPLES.md` foolproof-UI mandate) - only
  labels, one-line descriptions, and short empty-state status.
- No raw UUIDs in the UI - resolve to human-readable identifiers.
- Datetimes render via `lib/datetime.ts`/`useDatetime()`, never `new Date(iso)` on a backend
  timestamp directly.
- Every detail section renders, including when empty, with an explicit empty state - never hide
  a section on missing data.
- Tenant-facing UI never says "Foundryx" (white-label mandate); the sweep in section 5's T7
  rulings is the enforcement mechanism.

## 7. Responsive

- Usable and non-clipped at 375px AND 1280px - both verified per change (`agent-browser`).
- `DataGrid` scrolls sideways inside its own `overflow-x` container.
- Tab strips scroll, never wrap.
- Toolbars use `flex-wrap`; a record card's action group wraps under the identity at 375px (D5).
- Sheets/drawers pin to `h-dvh`/`100dvh` (a static `vh` can be eaten by a mobile browser's
  toolbar); side-pinned sheets that need internal padding use `top-*/bottom-*` + `max-h-[calc(
  100dvh-Npx)]`, never a uniform `inset-*` (which collapses the shared `side` variant's own
  `h-dvh`, AC-DLA-52).

## 8. Where the external skills plug in (`.claude/skills/feature/SKILL.md`)

| `/feature` step | Skill | Mode |
| --- | --- | --- |
| Step 1 grill | `animation-vocabulary` | Naming only |
| Step 2 UAC | `find-animation-opportunities` | Read-only; capped output becomes ACs or an explicit no-motion list |
| Step 5 Phase 1 (FE mock) | `animate` | Decision gate for any new motion added in Phase 1 |
| Step 8 review | `emil-design-eng` | Before/After/Why table on every UI diff |
| Step 8 review | `review-animations` | Only when the diff touches motion; runs as ONE `general-purpose` agent on Opus, never a `/code-review` fork |
| Any new FE dependency | `pick-ui-library` | First - repo picks already made: `motion`, `sonner`, `vaul`, `@dnd-kit` |
| Periodic | `improve-animations` | - |

Not used here: `animate-expo`, `write-swift`, `webapp-testing` (idle for this stack, D15).
