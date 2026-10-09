# sprint-5/12 AC-12-27 fix - agent-browser run log

Recorded 2026-09-22 by the lane coder, after the fix commit on branch
`sprint-5/12-mapping-master-formula-variables`. Tool: `agent-browser` CLI, `--session s50c`,
headless Chrome. NO Playwright. Widths 1280x900 and 375x812.
Target: **AC-12-27** (a document entity's mapping is resettable from the UI, header scope only).

## Verdict: AC-12-27 now PASSES on the UI path

"Reset to preset" is reachable on the surface a document entity actually lands on - the task
editor's **Mapping tab** (`components/task-editor-view.tsx`). It is the SAME action descriptor
and the SAME dialog the standalone `/mapping` page mounts: one shared
`useMappingResetAction` (`mapping/components/mapping-reset-action.tsx`), so gating, dirty-guard
behaviour and post-apply hydration cannot drift between the two surfaces.

## Stack under test

| Piece | Value |
|---|---|
| Frontend | :3012, FRESH prod build (`rm -rf .next && npm run build`, `npx next start -p 3012`) |
| Backend | :8012, uvicorn, lane env, DB `foundryx_service_s50` (unchanged - this fix is FE-only) |
| Auth | real login `demo@example.com` at `localhost:3012`, tenant `default` |
| Data | the tester's own company `E2E Docs s50 20260922-044247` (`7eab8612-...`), `sales_order` task, 11 header + 14 line mapping rows. Nothing was provisioned or deleted for this run. |

## Navigation - real clicks only

Sidebar `AutoCount` -> `Companies` -> row `E2E Docs s50 20260922-044247` -> tab `Entities` ->
the Sales order row's `Actions` menu -> `Configure mapping` -> (task editor, Mapping tab) ->
`Actions` -> `Reset to preset` -> `Reset mapping`.

A diff to reset was created through the product itself, by real clicks: `Edit` -> row 1's
`Source column` picker -> `DocKey` -> `Save task`. That is the `Changed  So number` row the
dialog then previews.

## Shots and artefacts

| File | What it proves | AC |
|---|---|---|
| `01-1280-entities-configure-mapping-menu.png` | The click path into a document mapping is unchanged: the row menu's `Configure mapping` | AC-12-27 |
| `02-1280-task-editor-mapping-tab-actions-present.png` | Where it lands (`?tab=mapping`) now carries an `Actions` menu beside `Edit` - the control the tester found missing | **AC-12-27** |
| `03-1280-actions-menu-reset-to-preset.png` | The menu open: one item, `Reset to preset` (the lifecycle items stay hidden on a draft task) | AC-12-21 |
| `04-1280-edit-mode-actions-hidden.png` | Edit mode: the `Actions` menu is gone (`Cancel` + `Save task` only) - the shell's `!editing` dirty guard, identical to the standalone page | AC-12-21 |
| `05-rows-before-reset.txt` | The 11 header + 14 line rows immediately before the reset, read from the API. Header row 1 is the deliberate bend `DocKey -> so_number` | AC-12-13 |
| `06-1280-reset-dialog-header-rows-only.png` | The preview dialog: preset badge `AutoCount SO`, `Changed  So number` first, 10 `Unchanged` rows, `Removed` section absent. **11 rows, every one a header field** - no `unit_price` / `qty_ordered` / `source_ref` / `line_number` | AC-12-22, AC-12-27 |
| `07-375-reset-dialog-header-rows-only.png` | The same dialog at 375: full-bleed, no clipping, `scrollWidth === innerWidth === 375` | AC-12-22, AC-12-33 |
| `08-1280-after-apply-toast-table-hydrated.png` | `Reset mapping` applied: `lib/toast` "Mapping reset to preset.", dialog closed, and the table behind it already shows the reset value (`DocNo -> So number`) | AC-12-23 |
| `09-rows-after-reset.txt` | The same read immediately after the apply | AC-12-13, AC-12-27 |
| `10-network-after-apply.txt` | The tail of the network log: `PUT .../mapping` (the bend), `POST .../reset-preset` (dry run), `POST .../reset-preset` (apply) - **and no `GET .../mapping` after it.** The table hydrated from the view the apply returned (`applyView`), not a refetch | AC-12-23 |
| `11-375-task-editor-mapping-tab.png`, `12-375-actions-menu-reset-to-preset.png` | The action at 375: reachable, menu clamped in the viewport, `scrollWidth === innerWidth === 375` | AC-12-33 |
| `13-375-reset-dialog-empty-diff.png` | Re-opened after the apply: "This mapping already matches the preset." with `Reset mapping` disabled - proof the apply landed | AC-12-22 |

## The line rows are untouched (read via the API, not the screen)

`diff` of the 14 `L` lines in `05-rows-before-reset.txt` vs `09-rows-after-reset.txt` is
**EMPTY** - all 14 line rows (including the operator's `SubTotal -> unit_price`) are
byte-identical across the reset. The only difference in the whole mapping is the header row the
reset was supposed to fix:

```
< H DocKey -> so_number string True     (before - the deliberate bend)
> H DocNo  -> so_number string True     (after  - the preset value)
```

## Console

Zero errors across the run. Only the codebase-wide Radix
`Missing Description or aria-describedby for {DialogContent}` warnings, which pre-date this plan.

## Run-log gotcha (for the next agent)

A dialog opened from an `ActionMenu` dismisses itself within ~12ms if the menu was opened with
the KEYBOARD (`focus` + `Enter`): the menu's close-auto-focus returns focus to the trigger and
the freshly-mounted Radix dialog reads that as a focus-outside. Reproduced identically on the
standalone `/mapping` page (unchanged code), so it is an interaction artefact of driving the
menu by keyboard, not a regression. Drive it with `click <trigger ref>` then
`find role menuitem click --name "..."` and the dialog stays open.
