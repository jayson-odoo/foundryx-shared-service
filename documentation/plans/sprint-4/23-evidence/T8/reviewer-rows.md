# Proposed `.claude/agents/reviewer.md` rows (AC-DLA-66)

`.claude/agents/reviewer.md` is gitignored and not present in this worktree - the coder cannot
edit it. These rows are the Sorento `documentation/reference/PR-CHECKLIST.md` "Apple Alignment"
and "Design" sections, adapted to this repo's component/file names plus D15 ("no Playwright
anywhere"). The main session applies them to its own gitignored copy.

## Apple Alignment (design-system, every screen)

- [ ] Status renders as a pill via `<StatusBadge status>` (the entity's status registry), not a
      hand-rolled coloured span.
- [ ] `DataGrid` rows use `rowHref` (or `onRowClick` only for an inline master-detail list); log
      and sub-tables carry no pointer cursor and no row action.
- [ ] No confirm dialogs on a destructive or detach action - the deferred grace-window model
      (`docs/reference/design-language.md` section 5, D2/D13) is used instead. The only
      exceptions are the named carve-outs that file's section 5 lists (module uninstall; tenant
      purge single-row + bulk typed-DELETE; Documents > Shares bulk revoke) plus the disclosed
      plain-confirm exceptions (Users' Impersonate; the tenant custom-status-edge fallback,
      BL-SS-052; the operator-console module Deactivate) - a confirm dialog anywhere else is a
      defect.
- [ ] The page renders exactly one `PageHeader` (no hand-rolled `<h1>`, no `ToolbarPageTitle`).
- [ ] Tab strips use `variant="line"` (the default) unless they are a two/three-option segmented
      switch, which pins `variant="default"` explicitly.
- [ ] Every icon-only button (`size="icon"`) has an `aria-label` or an `sr-only` label - a bare
      icon with no accessible name is a defect.
- [ ] **No Playwright anywhere (D15).** No `e2e/`, no `playwright*.config.ts`, no
      `@playwright/test` dependency, no new `.spec.ts` file, no revived `test:e2e` script.
      `[E2E]` = one recorded `agent-browser` CLI run per user flow (real clicks from the sidebar,
      375px AND 1280px, evidence under `documentation/plans/sprint-<N>/<NN>-evidence/<slice>/`) -
      guarded by `no-playwright.guard.test.ts` (AC-DLA-69).

## Design

- [ ] `docs/reference/design-language.md` section 3 hard-fails absent: `transition-all`,
      `scale(0)` entrance, `ease-in` entrance, a raw `cubic-bezier` outside `config.reui.css`,
      motion on a keyboard-initiated action, `PRESSED_CLASS` (or any `active:scale-*`) on a
      `cursor-grab` hold element.
- [ ] Primitives are from the roster (`docs/reference/design-language.md` section 4), not
      hand-rolled.
- [ ] No feature-explanation/how-to prose in the UI (foolproof-UI mandate).
- [ ] 375px and 1280px `agent-browser` screenshots attached, from a fresh
      `rm -rf .next && npm run build`.
- [ ] Any new motion honours `prefers-reduced-motion` (`useReducedMotion` from `lib/motion.ts`).
- [ ] Every dropdown is a `SearchSelect`/`MultiSelect` - no NEW bare `@/components/ui/select`
      import (`eslint.config.mjs`'s `no-restricted-imports`; the small pre-existing debt list is
      tracked BL-062/BL-SS-043, not to be widened).
- [ ] Every toast goes through `lib/toast.ts` - no direct `sonner` import outside its three
      sanctioned files (`lib/toast.ts`, `components/ui/sonner.tsx`,
      `components/platform/resource-actions/deferred-toast.tsx`).
- [ ] Every product table is a `DataGrid` - no raw `<table>`/`@/components/ui/table` outside the
      two content files (`form-renderer/table-field.tsx`, `email-editor/block-view.tsx`).

## Test cost

- [ ] New backend tests do not add whole-suite-running slow tests without cause; justify any new
      entry over ~2s.
- [ ] A test that only asserts against production-copy/live data is disclosed as such, not
      silently added to the gated suite.
