# Round-5 verify - Defect 2 (activate/run-now crash) + logging-sink warning

Lane s37, backend `:8007` (HEAD `3110490f`, not restarted this pass), frontend `:3007`
(fresh `3110490f` prod build, not rebuilt this pass). DB `foundryx_service_s37`. Browser:
`agent-browser --session s37-verify`, headless, real clicks from `/` via the sidebar (never a
deep URL). Run date 2026-09-12 (UTC).

**Tooling note (repeats the round-4 finding, confirmed again this pass):** plain `click`/CDP
mouse dispatch did not open Radix `DropdownMenuTrigger`s (row Actions menus), `RadioGroup`/
`ToggleGroup` items or menu items in this session, and did not register on the `DataGrid`
Actions button at all via a bare synthetic `click` event. A full synthetic pointer sequence
(`pointerdown` -> `mousedown` -> `pointerup` -> `mouseup` -> `click`, all at the element's real
`getBoundingClientRect()` center, `pointerType: 'mouse'`) dispatched via `element.dispatchEvent`
opened every Radix control reliably. This still drives the real component tree, the real
router and the real permission checks (no URL shortcut anywhere) - an environment/tooling
quirk, not a product defect. Plain `element.click()` continued to work for ordinary links/tabs
in most cases.

## Check 1+2 - Defect 2 closed + logging-sink warning (Warehouse task, Mocha company)

Company `Mocha 20260912T004004Z` (`d0b58883-6a87-46a3-abf1-0fe5aef8dd55`, `sinkImpl: logging`),
the SAME logging-sink company used throughout this plan's evidence. Task `warehouse`
(`autocount_http`, `/location`, list envelope, 21 rows), already `active` from the prior
pass - used the "if already active, Pause then Activate" branch of the brief.

Real clicks: Companies list -> Mocha row -> Entities tab -> Warehouse row's Actions menu ->
"Configure source" -> task editor opens on the Source tab (view mode, path `/location`
locked) -> Review & Activate tab.

1. **Before state** (`01-warehouse-review-before-pause-*.png`): task active, `Pause`/`Run now`
   visible, logging-sink warning NOT checked yet at this exact screenshot (checked from the
   next state onward).
2. **Pause** (real click via full pointer-sequence dispatch on the `Pause` button):
   `02-warehouse-paused-1280.png` - status flips in place to `Resume`/`Re-run preview`, **no
   crash, no reload**, `agent-browser errors` empty, `agent-browser console` empty. Logging-sink
   warning still present (`Runs on this company are logged only - no records are delivered
   until a Sorento target is set.`, verified via `document.querySelector('[data-testid=
   "activate-logging-sink-warning"]')`).
3. **Resume** (same technique): `03-warehouse-resumed-active-1280.png` - status flips back to
   `active` in place (`Pause`/`Run now` reappear), **no crash**, `errors` empty. Warning still
   present.
4. **Run now**: `04-warehouse-after-run-now-1280.png` - **no crash**, `errors` empty, console
   clean. Backend confirmed via `psql`: a NEW `ac_sync_run` row was written for this task
   (`id f827a62a-039d-4ddd-93ed-d98fa7a0b25c`, `job_id 69deffb0-00b6-46f6-bb3b-1336524d8d52`,
   `mode manual`, `rows_scanned 21`, `added 0 / updated 0 / deleted 0` - idempotent, matches
   the 21-row wrapper fact from the prior pass), `started_at 2026-09-12 12:20:34+09`.
5. **Runs tab** (`05-warehouse-runs-tab-new-run-*.png`, 1280 + 375): the new run row is visible
   ("12 Sept 2026, 11:20 Manual 21 0 0 - 0.8 s Success No changes"), matching the `psql` row
   above.
6. **Logging-sink warning banner** re-confirmed on the Review & Activate tab at both
   viewports (`06-warehouse-review-activate-warning-*.png`, 1280 + 375): the exact string
   `"Runs on this company are logged only - no records are delivered until a Sorento target is
   set."` renders via `data-testid="activate-logging-sink-warning"`; `Activate`/`Run now`
   stayed enabled the whole time (never blocked by the warning). No company's sink was
   switched to `sorento` at any point in this pass.

**Verdict: Defect 2 CLOSED at `3110490f`.** Zero crashes across Pause -> Resume -> Run now on
a real `autocount_http` task's in-place status transitions (the exact path that crashed every
time at `d696daba`); zero uncaught console errors (`agent-browser errors`/`console` both
empty throughout); the Runs tab shows the new run. The logging-sink warning is non-blocking
and visible at both viewports; Activate/Run now remained enabled.

## Staleness probe (added mid-pass at the coordinator's request; not fixed, only recorded)

New task created for this probe (a genuinely fresh, never-before-configured entity on the
same Mocha company - `unit_of_measure`, `autocount_http`, `/itembypage` `distinctOf`
preset), left in place (a real, harmless, correctly-configured `draft`-then-tested task, not
a throwaway - no cleanup performed, matching how AC-08-21 already left real entities on this
company):

1. Add entity "Unit of measure" -> Configure -> Source tab (view mode) -> **Test** (real click
   on `Test`): succeeded, preview grid shows `UNIT`/`DZ`/`SET` (3 distinct values).
2. Click **Edit** -> key/watermark/compared pickers appear pre-filled from the preset
   (`value` / `None` / "All except key columns") -> **Save task** (enabled): saved
   successfully ("Task saved." toast), tabs unlock, view mode returns.
3. **Test again** (same `Test` button, still on the Source tab, no navigation away): succeeded
   - confirmed via `psql`: `last_preview_at` advanced to `2026-09-12 12:24:00+09`,
   `etl_status` still `draft`.
4. **Without leaving the task editor**, click the **Review & Activate** tab directly (same
   mounted `TaskEditorView`, no route change, no reload):
   `07-staleness-probe-activate-disabled-*.png` (1280 + 375) - **`Activate` button is
   DISABLED** (`document.querySelector('button')` matching text `Activate`, `.disabled ===
   true`), despite step 3's Test having just succeeded server-side.
5. Navigated AWAY (breadcrumb -> company -> Entities tab -> the same Warehouse-style
   Actions -> "Configure source" on `unit_of_measure` again, a fresh route mount) and back
   into the SAME task's Review & Activate tab:
   `08-staleness-probe-activate-enabled-after-remount-1280.png` - **`Activate` is now
   ENABLED** (`disabled === false`) - the identical server state (`last_preview_at` from step
   3), only a fresh component mount changed.

**Staleness probe result: DISABLED within the same mount immediately after Test -> Save ->
Test again; ENABLED after leaving and re-entering the task editor (fresh mount/refetch).**
This corroborates the reviewer's suspicion: the in-editor Test-success handler updates
whatever local state drives the preview grid but does not refresh the `lastPreviewAt` (or
equivalent "previewed" flag) the Review & Activate tab's `Activate` gate reads, so the SAME
mount's Activate stays gated on a stale value until the next full load. No console errors or
crash accompanied this - it is a staleness/UX bug, not a crash, and is reported here as
requested; not fixed by the tester per the house rule (tester writes tests/records behavior,
never patches product code).
