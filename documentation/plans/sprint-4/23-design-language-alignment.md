# 23 - Design language alignment (Sorento parity)

> The design that fulfils `23-design-language-alignment-acceptance-criteria.md`. That file is
> the contract; where this plan and the UAC disagree, the UAC wins.
> Governs: `PRINCIPLES.md` > `docs/reference/design-language.md` (created in T8) > installed
> design skills (`apple-design`, `emil-design-eng`, `animate`, `review-animations`,
> `find-animation-opportunities`).

**Slug:** `design-language-alignment` | **Domain:** design-system (cross-cutting, every screen)
**Status:** APPROVED - grill 4 Sep 2026 (8 decisions), lavish plan review 4 Sep 2026 (A1 delete
demo pages, A2 no Playwright = D15, widened at review close to a full purge = slice T0).
T0 and T1 in progress (parallel worktrees `s23-t0`, `s23`; disjoint files).
**Branch:** base `origin/main`; worktree `.claude/worktrees/s23`; integration branch
`sprint-4/23-design-language-alignment`; one branch per slice `sprint-4/23-T<n>-<slug>`, PR
each, `/code-review` between slices, one coder at a time.
**Sibling source of truth:** `/Users/tehjayson/Documents/foundryx/sorento_crm` - read every
reference file with `git -C <that path> show origin/main:<file>` (the local checkout there is
on a stale fix branch). Motion Round 2 material lives on
`origin/integration/ui-motion-round2:<file>`. The research reports that produced this plan:
session scratchpad `sorento-design-standard.md` (6.8k lines, every Sorento file quoted) and
`shared-service-ui-census.md` (every baseline count with `file:line`).

---

## 1. What is being built, in one paragraph

The shared-service frontend adopts Sorento's shipped design language so both products read as
one system: motion, material, z and type tokens defined once; a critically damped spring on
every surface via `lib/motion.ts`; pressed feedback and 44px touch targets on every control;
translucent header and sidebar; pills that are round; tabs that are underlines and scroll;
grids with sticky headers, resizable and movable columns, rows that are real links, rows that
stay on screen while the next page loads, and a Back that lands on the row you left; one
`PageHeader` with menu-derived crumbs; the Sorento D6 record header (pager, gear, primary);
confirm dialogs replaced by a tenant-scoped server-deferred grace window; route-level loading,
error and not-found shells; a sonner wrapper; the three accessibility preference blocks; and
the inventory tests, lint rules and reference doc that keep all of it from drifting. What stays
different is deliberate: orange primary, Poppins headings, soft-trash where the entity already
has it, and the `ctx`/`i` server-driven record-nav this repo's Resource shell is built on.

## 2. Why now (evidence, measured 4 Sep 2026 on `e58ae9b`)

- 0 motion/material/z tokens; every easing and duration is a per-component literal; 1 raw
  `cubic-bezier` (`switch.tsx:86`), 12 `transition-all`, 18 literal `duration-N`, 69 `text-[Npx]`.
- 0 `prefers-reduced-motion` / `-transparency` / `-contrast` handling anywhere.
- `button.tsx` has no pressed state and no coarse-pointer target; sizes are 28-40px.
- All 24 surface animations are tw-animate keyframes (not interruptible); `motion` is imported
  only by 16 decor components with zero importers; `vaul` has zero importers; 3 `TooltipProvider`
  mounts with `delayDuration={0}`.
- `DataGrid` defaults: `headerSticky false`, `columnsResizable false`, `columnsMovable false`;
  rows are `onClick` + `router.push` (no anchor, no keyboard, no middle-click, no prefetch);
  no placeholder dim - every page turn drops to skeleton rows.
- 0 `loading.tsx` / `error.tsx` / `not-found.tsx` for 124 page segments; 7 pages and both
  shared loaders render the string `Loading...`.
- 79 pages use the Metronic `ToolbarPageTitle`; `resource-form` inlines its own header with
  crumbs, nav, Save/Edit, `...` and Back all on one row.
- 41 `confirm:` action configs + one shared `ConfirmActionDialog`; 26 `ui/table` importers
  (21 of them Metronic `account/**` demo pages) and 4 raw `<table>`.
- 97 direct `sonner` imports; ~180 of 245 icon buttons without an accessible name; 45 files
  with raw `<button>`; 0 lint a11y rules; 0 CSS/classname guardrail tests.
- Already right, kept: `ResourceAction.surfaces` registry shared by row/bulk/form menus;
  `lib/list-context.ts` `ctx`/`i` URL carry; server-driven circular `use-record-nav.ts`;
  `status-badge` registry; `useDebounce`; `--mono`/`--success`/`--info`/`--warning` tokens.

## 3. Standards (the design)

### 3.0 Playwright retirement (T0)

No Sorento file to read; this is a deletion. Remove `service_frontend/e2e/`, the three
`playwright*.config.ts`, `playwright-report/`, `test-results/`, the `test:e2e` script, the
`@playwright/test` dependency (`npm uninstall @playwright/test --package-lock-only`: the shared
`node_modules` symlink must not be rewritten), the three `.gitignore` lines, and every live
mention (docs, skills, agents, CI, code comments) outside `documentation/plans/**`. Replace each
removed sentence with the agent-browser rule, never leave a hole. Add
`service_frontend/no-playwright.guard.test.ts` (walks the repo from the frontend root's parent,
skips `node_modules`, `.next`, `.git`, `documentation/plans`, `.claude/worktrees`; fails on any
case-insensitive `playwright`). Evidence for `[E2E]` from T1 on = agent-browser runs only.

Each subsection names the Sorento file to read first. Port the mechanism, adapt the names to
this repo, keep this repo's layering (UI -> hook -> service trio -> `lib/api-client`).

### 3.1 Tokens, CSS, preferences (T1)

Read `sorento: sorento_crm_frontend/css/config.reui.css`, `css/styles.css`,
`css/design-tokens.test.ts`.

- `css/config.reui.css` `:root` + `.dark`: the material block (`--material-regular/thick`,
  `--material-blur`, `--material-edge`, `--scrim`), the z-scale (`--z-header/sidebar/banner/
  modal/sticky-content/sticky-content-corner`), the motion block (`--ease-standard`,
  `--duration-fast/base/slow`), `--grid-max-h: calc(100dvh - 17rem)` (toolbar + header +
  pager; overridable). `@theme`: `--default-transition-timing-function`,
  `--default-transition-duration`, the type scale with per-step tracking/leading exactly as
  Sorento (keep this repo's `--text-2xs`/`--text-2sm` values if they already match).
  `--font-sans` stays Inter, `--font-heading` stays Poppins (D4) - both remain in
  `foundryx-tokens.css` since they are brand.
- `css/styles.css`: `body { font-optical-sizing: auto }`, `@utility material-regular /
  material-thick / material-edge`, then the three preference blocks LAST in the file (verbatim
  from Sorento, plus the M3 additions: `.demo1 .sidebar, .demo1 .wrapper, .demo1 .header
  { transition: none !important }`, `[data-vaul-drawer] { transition-duration: 1ms !important }`,
  `[class*='transition-['] { transition-duration: 1ms !important }`).
- Shell: `header.tsx` class `bg-background` -> `material-regular material-edge border-b`;
  `sidebar.tsx` -> `material-thick`; impersonation banner uses `z-(--z-banner)` and pushes the
  header down (`top` offset via a CSS variable the banner sets), never overlays it.
- Literal sweep: `switch.tsx:86` -> `ease-(--ease-standard) duration-(--duration-slow)`;
  `progress.tsx` -> `transition-transform` / `transition-[stroke-dashoffset]`;
  `input-otp.tsx:44` -> `transition-[color,border-color,box-shadow]`; `company-documents.tsx`
  goes with the `account/**` deletion (T7) - if D8 is reversed, it takes
  `transition-[stroke-dashoffset] duration-(--duration-base)`; the 69 `text-[Npx]` become the
  nearest `text-2xs/xs/2sm/sm` step (demo2-10 layouts are deleted in T7; until then they are
  exempt in the test).
- `css/design-tokens.test.ts`: reads the CSS files and resolves tokens through jsdom computed
  style for AC-DLA-01..05, 07; greps `app/**`, `components/**`, `css/**` for AC-DLA-06 with
  an allowlist constant at the top of the file.

### 3.2 Primitives (T2)

Read `sorento: components/ui/primitive-classes.ts`, `button.tsx`, `badge.tsx`, `tabs.tsx`,
`data-grid.tsx`, `data-grid-table.tsx`, `data-grid-pagination.tsx`, `sheet.tsx`,
`alert-dialog.tsx`, `tooltip.tsx`, and on the integration branch `components/ui/
pressed-class.inventory.test.tsx`, `data-grid-table.tsx` (M4 prefetch + placeholder).

- `components/ui/primitive-classes.ts` verbatim from Sorento, with `PRESSED_CLASS` already
  carrying the M1 duration/ease tokens.
- `button.tsx`: base gains `PRESSED_CLASS`; `size` `lg`/`md`/`icon` gain
  `COARSE_HIT_TARGET_CLASS`; `sm` does not (dense clusters: pagination). Same on checkbox,
  switch, radio, toggle, `TabsTrigger`, slider thumb; `PRESSED_CLASS` on `DropdownMenuItem`,
  `ContextMenuItem`, `MenubarItem`, `CommandItem`.
- `badge.tsx`: `rounded-full` base, `md` `h-6 px-2.5`, `sm` `h-5 px-2`; `appearance`
  `light` | `outline`; delete `ghost` and the `lg`/`xs` sizes unless a call site proves a need
  (grep first; `status-badge.tsx` passes `size`). `BadgeDot` stays; `status-badge.tsx` renders
  the 6px dot with the registry `hex` as today.
- `dialog.tsx` / `alert-dialog.tsx` / `sheet.tsx`: `modal ?? true`; overlay = `OVERLAY_CLASS`
  (T3 swaps Dialog/Sheet to `OVERLAY_CLASS_STATIC` when they move to the spring); height caps
  and `SheetBody` scroll as AC-DLA-10; `DialogClose` ring.
- `tabs.tsx`: default `variant: 'line'` in both cva blocks and the context; base list
  `flex items-center shrink-0 min-w-0 max-w-full overflow-x-auto [scrollbar-width:none]
  [&::-webkit-scrollbar]:hidden` plus the right-edge mask when a `ResizeObserver` says it
  overflows. Pin `variant="default"` on the segmented keepers (`resource-list` Active|Trashed,
  card/list toggle, any 2-3 option switch found by grep) and nowhere else.
- `data-grid.tsx` defaults flip (AC-DLA-13); `data-grid-table.tsx` gains the scroller
  (`DataGridScroller`: `overflow-x-auto overscroll-x-contain`, fade via mask when
  `getTotalSize() > clientWidth`, `min-w-max` on the table in that case), pinned first
  non-select column under `sm` through TanStack `columnPinning`, `tabular-nums` on `<tbody>`,
  `LinkableBodyRow` (`rowHref`, `role="link"`, keyboard, `onAuxClick`, pointer-enter
  `router.prefetch` once per href via a `Set` ref, `active:bg-muted/60`, `transition-opacity`),
  `data-returned` highlight, `isPlaceholderData` -> `opacity-60` body. `data-grid-pagination.tsx`
  gates its skeletons on `isLoading && rows.length === 0`.
- `tooltip.tsx` bare `Root`; `providers/tooltips-provider.tsx` is the ONE provider
  (`delayDuration 700`, `skipDelayDuration 300`); remove the wrapper from `theme-provider.tsx`.
- `sonner.tsx`: `position="top-center" closeButton`; `query-provider.tsx` drops its per-call
  `position`.

### 3.3 Motion (T3)

Read `sorento: lib/motion.ts`, `lib/motion.test.ts`, `components/ui/dialog.tsx` (full),
`sheet.tsx`, `popover.tsx`, `dropdown-menu.tsx`, `drawer.tsx`; on the integration branch
`lib/motion.ts` (M2: `MENU_SPRING`, `SURFACE_SPRING_EXIT`, `surfaceExitTransition`),
`alert-dialog.tsx`, `command.tsx`, `dropdown-menu.tsx` SubContent, `context-menu.tsx`,
`hover-card.tsx`, `menubar.tsx`. Sorento main has AlertDialog, Tooltip and SubContent still on
keyframes; this repo ships them on the spring from the start (D1).

- `lib/motion.ts` = Sorento's file plus the M2 exports. Pattern per surface: `useOpenState`
  mirrors the Radix root; `<AnimatePresence>` gates a `motion.div` inside `Content` with
  `surfaceVariants(reduced)` and `transition={surfaceTransition(reduced, kind)}` /
  `exit` on `surfaceExitTransition(reduced)`; `forceMount` on the Radix Content so Radix's own
  Presence does not race the spring; overlay opacity is driven by the same spring on
  `OVERLAY_CLASS_STATIC`; origin via `origin-(--radix-popper-content-transform-origin)`.
  `Sheet` = slide-only variants per side (no scale). `Select` content follows Popover.
- `command.tsx` `CommandDialog` takes `motion={false}` and renders `DialogContent` with
  `transition={{ duration: 0 }}` and no scale; the global search opener passes it. Any other
  keyboard-shortcut-opened surface does the same.
- `header.tsx` mobile nav: `Sheet` -> `Drawer` (vaul, `direction="left"`, overlay
  `OVERLAY_CLASS_STATIC`, `shouldScaleBackground={false}`); the mega-menu mobile sheet follows.
- `css/demos/demo1.css`: `--sidebar-transition-duration/timing` -> `var(--duration-slow)` /
  `var(--ease-standard)`; hover-expand rule wrapped in `@media (hover: hover) and (pointer:
  fine)`; the width transition wrapped in `@media (prefers-reduced-motion: no-preference)`;
  `demo1/layout.tsx` `setTimeout(1000)` -> `requestAnimationFrame` double-frame. The
  transform-only rewrite is NOT attempted here (Sorento tried and reverted it); the trace
  decides (AC-DLA-24).
- Delete the 16 decor components and `framer-motion`; `components/ui/
  deleted-motion-components.guard.test.ts` asserts none returns.
- `find-animation-opportunities` was consulted through Sorento's audit B: the only additions
  this repo takes are the six that passed there and exist here (row dim on pending, badge
  count pop on the notification bell, jobs-drawer Ready cluster, wizard step slide on the
  channel-connect and import wizards, pressed sweep, countdown bar). Nothing else animates.
  The ten rejected candidates in Sorento's plan section 6 are not re-proposed.

### 3.4 Header, wayfinding, rows, list latency (T4)

Read `sorento: components/common/PageHeader.tsx`, `DetailActions.tsx`, `ListPager.tsx`,
`PageHeader.inventory.test.ts`, `lib/listNavQuery.ts`; on the integration branch
`data-grid-table.tsx` (`from=` restore, `appendListState`), `hooks/useListPager.ts` (prefetch).

- `components/platform/page-header/page-header.tsx`: `{ title, eyebrow?, crumbs?, actions? }`;
  crumbs from `useMenu().getBreadcrumb(MENU_SIDEBAR)` (already exists in `hooks/use-menu.ts`),
  terminology-aware like `ToolbarPageTitle` was (`termKey` on the menu item), root crumb
  "Dashboard", last crumb `BreadcrumbPage`. `ResourceList` renders it above its card (the
  list's primary Create button is the `actions` slot); `resource-form` renders it as the
  toolbar row with Back as `actions`. The 79 `ToolbarPageTitle` sites and the 7 `<h1>` sites
  migrate one module per commit; `app/components/partials/common/toolbar.tsx` keeps
  `Toolbar`/`ToolbarActions` for non-resource pages but `ToolbarPageTitle` is deleted.
- `resource-form.tsx` header (lines 87-193 today) becomes: toolbar row = `PageHeader` with
  `actions={<BackToList/>}`; record card top = identity (avatar, `h1` title, subtitle) left and
  `RecordActions` right: `[RecordNav] [gear: ActionMenu surface="form" ordered secondary,
  separator, destructive] [primary]`. `ActionMenu` gains a `trigger="gear"` icon variant and
  orders `tone: 'destructive'` items last after a separator. The dirty-guard `AlertDialog`
  stays (it is not a destructive confirm).
- `resource-list.tsx`: `rowHref={(row) => \`${config.rowHref(row)}?ctx=${ctx}&i=${idx}&from=${row.id}\`}`
  instead of `onRowClick` when the config has a navigable href; keep `onRowClick` only for
  `onRowSelect` (inline master-detail) lists. `lib/list-context.ts` gains `from` helpers
  (`parseListNav`, `buildListNav`) so `use-record-nav.ts` and Back can carry it unchanged.
- `hooks/use-resource-list.ts`: keep `rows` while `isLoading` after the first successful load
  and expose `isPlaceholderData = isLoading && rows.length > 0`; `ResourceList` forwards it and
  drops the 3 `disabled={isLoading}` toolbar guards.
- `hooks/use-record-nav.ts`: on mount resolve prev/next ids (one `fetchAt` each, already how
  `goPrev`/`goNext` work) and `router.prefetch` both hrefs; carry `from=<currentId>`.
- `app/components/layouts/demo1/components/sidebar-menu.tsx`: `prefetch={false}` on `Link`
  plus `onPointerEnter={() => router.prefetch(href)}` (once per href).
- Labels: verb + noun on every primary; `page-header.inventory.test.ts` also greps for
  `id.slice(`/`id.substring(` fallbacks in titles.

### 3.5 Deferred actions (T5) - the one backend slice

Read `sorento: sorento_crm_backend/app/api/v1/system/pending_actions.py`,
`app/services/form_action_registry.py` (`FormAction`), `app/services/form_action_grace.py`,
`sorento_crm_frontend/hooks/useDeferredAction.tsx`, `components/common/DeferredActionButton.tsx`,
`components/common/deferredToast.tsx`, `documentation/reference/ADR-PRODUCT-STANDARDS.md`
section 2. This repo has no `sla_form_actions` engine to generalise, so the engine is new and
small; it follows the repo's registry idiom (`app/jobs/registry.py`).

Backend (`service_backend`):
- `app/models/pending_action.py` `PendingAction` (columns as AC-DLA-37; `payload_json`
  `JSON(none_as_null=True)`; `status` string with a CHECK; partial unique index
  `uq_pending_actions_one_per_record`). `tenant_settings` gains the two nullable integer
  columns; the settings schema/service/router (`catalog.py` owns `tenant_settings` today -
  move the general settings read/write into a `tenant_settings` router if `catalog.py` is the
  wrong home, one commit) expose `deferredDestructiveSeconds` / `deferredReversibleSeconds`.
- `app/deferred_actions/registry.py` `DeferredActionDef` + `register_deferred_action` +
  `deferred_action_for(key)` (loud on unknown/duplicate, `_reset_registry_for_tests`);
  `app/deferred_actions/service.py` `park`, `cancel`, `current`, `commit_due(db)`,
  `commit_one(db, row)` (own transaction per row, `failed` + `error_text` on exception,
  `ineligible` folded into `failed` when the entity is gone); `app/deferred_actions/
  handlers.py` registers the first-party keys by calling the existing services
  (`UserService.trash`, `RoleService.delete`, `WorkflowService.trash`, ...). Window seconds =
  `tenant_settings` value or the default per `window`.
- `app/api/v1/pending_actions.py`: the three routes (AC-DLA-39/40), camelCase wire
  (`validation_alias`), `ApiModel` for the datetimes, permission = the def's slug resolved
  through the same `require_permission` resolver (fresh from DB), actor via
  `get_actor_user_id`, uniform 404 cross-tenant. Mounted under `/api/v1`.
- Beat: `pending_actions.commit_due` task in `app/workflow_engine/worker.py`
  `beat_schedule` (60s, same host as the other sweeps; guarded import). Eager dev = the
  frontend's lapse-time `GET current` lazily commits (AC-DLA-41).
- Tests first (pytest, Postgres): park/idempotent/409/400/403, cancel before and after,
  current lazy commit, sweeper with a frozen clock, handler failure isolation, cross-tenant
  404, window from settings, impersonation actor.

Frontend (`service_frontend`):
- `services/pending-actions-service.{ts,mock,real}.ts` (park, cancel, current) - the mock is
  Phase 1, swapped at the boundary in Phase 2.
- `hooks/use-deferred-action.ts` (state machine as AC-DLA-43, focus-poll of `current`,
  `dimEntityIds` for bulk); `components/platform/resource-actions/deferred-action-button.tsx`
  (`DeferredCountdown`: `scaleX` fill from `origin-left`, one linear transition set once via
  double rAF, 1000ms tick for the `role="timer"` label, `motion-reduce:transition-none`,
  Cancel); `deferred-toast.tsx` (sonner toast with the bar and Cancel, row `data-pending`);
  `ResourceAction.deferred` wired in `action-menu.tsx` (form surface hands the countdown to the
  record card's primary area; row surface fires the toast) and `bulk-actions.tsx` (one action,
  count label, all selected rows dim). Commit -> `runtime.reload()` + toast; a deleted record
  page navigates to the list with its `ctx`/`i`/`from`.
- Settings > General: two `FormRow` number fields, 1-60, through the existing settings
  service trio and provider.
- The 41 `confirm:` configs migrate to `deferred:` one module per commit; the two typed
  carve-outs keep `confirm.input`; `confirm-carve-outs.inventory.test.ts` pins them.
- Recorded agent-browser run (dedicated tenant, timestamped names, real clicks, both widths, a
  second tab open for countdown parity) under `23-evidence/T5/`. No Playwright (D15).

### 3.6 Shells (T6)

Read `sorento: components/common/ListPageSkeleton.tsx`, `app/(protected)/
loading-inventory.test.tsx`, `ListSearchInput.tsx`, `hooks/useDebouncedSearch.ts`; on the
integration branch `lib/toast.ts`, `lib/toast.inventory.test.ts`.

- `components/platform/skeletons/{list-page-skeleton,record-page-skeleton}.tsx`; one
  `loading.tsx` per list/record segment re-exporting the right one (mechanical; the inventory
  test enumerates segments by grepping for `ResourceList`/`DataGrid`/`ResourceForm`).
- `app/(protected)/error.tsx` (`'use client'`, `reset`, rendered inside `Demo1Layout` so the
  chrome survives) and `not-found.tsx`.
- `lib/toast.ts` wrapper; the 97 importers switch one module per commit.
- `components/platform/list-search-input.tsx` adopted by `ResourceList`, `SearchSelect`,
  `MultiSelect`, the palette search; `useDebounce` default stays 300 for non-search callers.
- `dvh` on the four sheets/drawers; `input.tsx` `pointer-coarse:text-base`.

### 3.7 Sweep (T7)

- `account/**` and `demo2`-`demo10`: delete routes, components, menu entries, css, e2e
  references including `e2e/account-security.spec.ts` (confirmed at plan review, D8/D15).
- The 7 real raw-table surfaces migrate to `DataGrid` (embedded, `tableLayout` defaults now
  give sticky header + resizable + movable); `imports/page.tsx` becomes a `ResourceList`
  config (it is a paginated list).
- Press sweep (45 files), aria-label sweep (~180 sites), skip link, `role="content"`, ring on
  `outline-none` sites, `useForm` mode.
- Inventory tests: `pressed-class`, `a11y-guardrails`, `ui-table`, `deleted-motion-components`.

### 3.8 Guardrails and docs (T8)

- `eslint.config.mjs` rules as AC-DLA-63 (the `text-[Npx]` rule is Sorento's local AST rule,
  port it from `sorento: eslint.config.mjs`).
- `docs/reference/design-language.md` (the `docs/reference/` tree exists only in the user's
  uncommitted docs refactor on 4 Sep; T8 lands after it, or creates the folder) = Sorento's
  `DESIGN-LANGUAGE.md` re-homed: this repo's
  file paths, this repo's roster (`ResourceList`, `ResourceForm`, `PageHeader`, `ActionMenu`
  gear, `DeferredActionButton`, `StatusBadge`, `SearchSelect`/`MultiSelect`, `ClampedText`,
  `OverflowPills`, `ListSearchInput`, `lib/toast`), decisions D1-D14, the frequency gate, the
  hard-fails. `frontend-design-language.md` keeps Resource-shell + canvas content and links.
- `PRINCIPLES.md` hard-fail additions, `CLAUDE.md` map bullet + index row,
  `.claude/agents/reviewer.md` checklist rows, `.claude/skills/feature/SKILL.md` design slots.
- D15 in the process docs: PRINCIPLES.md methodology step 7 + DoD gate, `/feature` steps 5/6,
  `.claude/agents/tester.md`, `CLAUDE.md` commands, `docs/reference/process-lessons.md`:
  "one recorded agent-browser run per user flow" replaces "one Playwright E2E per user flow";
  `npm run test:e2e` stops being a gate; the `webapp-testing` skill is marked idle for this stack.
- `/review-animations` over the integrated diff; verdict table into the T8 PR.

## 4. Slices and order

| Slice | Branch | Contents | Phase 1 (mock) | Phase 2 (tests) |
|---|---|---|---|---|
| T0 | `sprint-4/23-T0-playwright-retirement` | 3.0 | n/a | guard test; lint + test + build green |
| T1 | `sprint-4/23-T1-tokens` | 3.1 | n/a | `design-tokens.test.ts`; light + dark shots |
| T2 | `sprint-4/23-T2-primitives` | 3.2 | n/a | vitest per primitive; 375 sweep of Users, Settings, Services, a workflow |
| T3 | `sprint-4/23-T3-motion` | 3.3 | n/a | `motion.test.ts`, guard test; frame-by-frame + reduced-motion evidence; sidebar trace |
| T4 | `sprint-4/23-T4-header-rows-latency` | 3.4 | `PageHeader` + `RecordActions` against the existing mocks | inventory tests; `use-resource-list` placeholder test; `use-record-nav` prefetch test; Users and Statuses evidence |
| T5 | `sprint-4/23-T5-deferred-actions` | 3.5 | button + toast + settings fields against `pending-actions-service.mock` | pytest test-first; vitest hook; agent-browser run incl. a real 10s lapse and a second tab |
| T6 | `sprint-4/23-T6-shells` | 3.6 | n/a | loading inventory; toast inventory; 375 Safari-emulated evidence |
| T7 | `sprint-4/23-T7-sweep` | 3.7 | n/a | pressed/a11y/table/deleted inventories; full sidebar sweep evidence |
| T8 | `sprint-4/23-T8-guardrails-docs` | 3.8 | n/a | lint green in CI; `/review-animations` Approve |

Order T0 (parallel with T1, disjoint files) -> T1 -> T2 -> T3 -> T4 -> T5 -> T6 -> T7 -> T8. T2 depends on T1 (tokens); T3 on T2
(`OVERLAY_CLASS_STATIC`, `primitive-classes`); T4 on T2 (`rowHref`, `isPlaceholderData`) and
T3 (`AlertDialog` spring for the dirty guard); T5 on T4 (`RecordActions` seam) and T3
(`AlertDialog` for the carve-outs); T6 on T2 (toast position) and T5 (`deferred-toast` lives
beside `lib/toast`); T7 on T2 (`PRESSED_CLASS`); T8 last. T5 may run in parallel with T6 in a
second worktree only if the two coders touch disjoint files (T5 = backend + `resource-actions`;
T6 = `loading.tsx` files + `lib/toast`), otherwise sequential.

Evidence: `documentation/plans/sprint-4/23-evidence/T<n>/` (`README.md` with the run log and
verdict lines, screenshots named `NN-<surface>-<width>.png`). Test report per slice:
`23-design-language-alignment-test-report.md` appended per slice (AI_Agent_Orchestration_Guide
section 6 format, keyed to AC ids).

## 5. Testing seams (agreed before Phase 2)

- Token and class inventories read source files from disk (`readFileSync` over a glob) with
  allowlist constants at the top of each test; a brace-and-quote-aware tag finder (port
  Sorento's `findButtons`/`openTags`) for JSX scans.
- Motion: jsdom `matchMedia` stub for `prefers-reduced-motion` and `pointer: coarse`; `motion`
  mocked to synchronous for variant assertions; the interruptibility claim is browser evidence,
  not a unit test.
- Deferred actions: pytest on Postgres seeding its own tenant + user chain; a frozen clock for
  the sweeper; RBAC denial per key; the frontend hook tested with the mock service and fake
  timers.
- `use-resource-list`: a fetcher that resolves on demand; assert rows persist and
  `isPlaceholderData` flips.
- Browser evidence via agent-browser (sidebar clicks from `/`, 375 and 1280), frame reviews
  through the DevTools Animations panel at 4x. No Playwright anywhere (D15): every `[E2E]` AC
  is an agent-browser run, and T8 rewrites the process docs to match.

## 6. Not built (registered in `documentation/backlogs/backlog.md`)

- TanStack Query adoption for lists (page-scoped client pager like Sorento D4) - BL-SS-045.
- Sidebar collapse transform-only rewrite - gated on the T3 trace - BL-SS-046.
- Dark-mode toggle (tokens defined, no switch) - BL-SS-047.
- Canvas node add/remove and context-menu motion (React Flow surfaces) - BL-SS-048.
- Sync-back: when Sorento merges Motion Round 2, diff the two `lib/motion.ts` and
  `design-language.md` files - BL-SS-049.
- `form-renderer/table-field.tsx` and `email-editor/block-view.tsx` stay content tables - no
  backlog, recorded as the allowlist.
- Rubber-banding on any resizable panel, `ssr: false` provider review, a stronger ease-out
  curve: not proposed (Sorento's rulings stand).

## 7. Risks

- `modal ?? true` flips every dialog at once; the workflow canvas drawer, the conversation
  drawer and the jobs drawer are utility sheets - they pass `overlay={false}` / `modal={false}`
  explicitly and are on the T2 browser checklist.
- `headerSticky` needs a bounded scroller: a `DataGrid` inside a dialog or tab with its own
  scroll container may double-scroll; the default is per-list overridable and T7's sweep
  covers every embedded grid.
- Keeping previous rows while a filter changes can show a mismatched header for one frame on
  a list whose column set depends on the view (Active|Trashed adds Restore); the dim makes it
  legible; verify on Users.
- Deleting `account/**` and `demo2-10` (confirmed) removes routes some bookmark may point at;
  `not-found.tsx` (T6) catches them inside the shell, and the PR lists every removed path.
- The 97 sonner and 79 `ToolbarPageTitle` migrations are mechanical but wide: one module per
  commit so a regression is bisectable; the inventory tests define done.
- The deferred engine commits within 60s of the window when the tab is closed (beat tick) -
  that is the guarantee, not "at exactly commit_at"; the UAC says so.
- `pending_actions` reuses each entity's existing permission; no new permission means no grant
  sweep, but the T5 PR must show the resolver call per key.
