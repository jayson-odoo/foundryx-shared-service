# SS-MAIN-RED-VITEST: main went red on a migration form test race

Lane SS-MAIN-RED-VITEST, branch `crew/ss-main-red-vitest`, base `a2cd8da5` (main).

## Symptom

Push CI on main `a2cd8da5` (run 43131804059, 12 Nov 01:03Z), job "Test frontend (lint + vitest)":
1 failed | 513 passed test files. The one failure:

`app/(protected)/omnichannel/settings/migration/components/migration-form-view.test.tsx`
> MigrationFormView - unreadable source channels (AC-44-23) > changing a readable channel target afterwards keeps the Skip entry

`TestingLibraryElementError: Unable to find an accessible element with the role "combobox" and name "Target channel for Support line"` at line 500.
The DOM dump shows the "Skip this channel" picker still mounted (`role="dialog" data-state="closed"`) and the page behind it
still `aria-hidden="true"` (Radix modal popover `hideOthers`).

## Cause

Not #232 / #233: neither touches omnichannel, `SearchSelect`, `components/ui/popover.tsx` or the vitest setup
(`git diff --name-only 7b9335b6 a2cd8da5 -- service_frontend`). The test has not failed in any earlier run
(17 failed runs since 10 Nov scanned; none name this test). It is a timing race in the test:

- `PopoverContent` closes through `motion` `AnimatePresence` (`components/ui/popover.tsx`, design-language T3).
  `MotionGlobalConfig.skipAnimations` (`vitest.setup.ts:24`) makes the exit instant but its completion and the React
  commit that unmounts the content (and lifts `aria-hidden`) still land on a later task, not inside the click.
- `chooseSkipFor` clicks the option and returns. The test then `waitFor`s a react-hook-form value that is written
  synchronously by the click, so `waitFor` passes on its first check and yields only RTL's one `setTimeout(0)` drain.
- The next line queries the readable channel's combobox synchronously. Locally the unmount commit wins (measured: picker
  gone ~3 ms after the click); on the loaded CI runner the `setTimeout(0)` won once, so the combobox was still hidden.

Deterministic red: querying the combobox right after the click (no yield) fails with the exact CI error and DOM.

## Fix (test side; product behaviour is correct)

The close animation and the modal `aria-hidden` until it ends are intended (T3, `vitest.setup.ts:10-23`). The test
assumed a synchronous close. `chooseSkipFor` now waits until the picker has closed (its listbox is gone) before it
returns, so every caller queries the page only after the popover unmounted. No assertion is removed or loosened.
The same helper also protects "choosing Skip adds the id ..." whose `rowSelect` query has the same exposure.

## Verification

- Red proof: the probe above fails on base; the fixed helper passes.
- Whole frontend vitest + lint locally; CI green on the PR head.
